from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from config import (
    CRC_PLACEHOLDER,
    DIST_STEP_MAX,
    DIST_STEP_WIDTH_M,
    DOOR_ID_MAX,
    DOOR_ID_MIN,
    SHEET_UNIT_ID_IS_1_BASED,
    STOP_ERROR_FALLBACK_MAX_GAP_M,
    STOP_ERROR_MATCH_TOL_M,
    USE_CRC_PLACEHOLDER,
)
from data_loader import MovementDataRepository, MovementRow


@dataclass
class DoorCommand:
    dcu_idx: int
    cmd: str
    dir: str
    dist_step: int


class CommandBuilder:
    def __init__(self, repo: MovementDataRepository, platform_id: int) -> None:
        self.repo = repo
        self.platform_id = platform_id

    @staticmethod
    def _normalize_dir(direction: str, move_distance_m: float) -> str:
        d = (direction or "").strip().lower()
        if d == "left":
            return "Left"
        if d == "right":
            return "Right"
        if d == "both":
            return "Both"
        if move_distance_m < 0:
            return "Left"
        if move_distance_m > 0:
            return "Right"
        return "None"

    @staticmethod
    def _merge_dir(old_dir: str, new_dir: str) -> str:
        if old_dir == new_dir:
            return old_dir
        if old_dir == "None":
            return new_dir
        if new_dir == "None":
            return old_dir
        return "Both"

    @staticmethod
    def _distance_m_to_step(distance_m: float) -> int:
        raw = abs(distance_m)
        if raw <= 0:
            return 0
        step = int(round(raw / DIST_STEP_WIDTH_M))
        if step < 1:
            step = 1
        if step > DIST_STEP_MAX:
            step = DIST_STEP_MAX
        return step

    @staticmethod
    def _sheet_unit_to_dcu_idx(unit_id_from_sheet: int) -> int:
        if SHEET_UNIT_ID_IS_1_BASED:
            return unit_id_from_sheet - 1
        return unit_id_from_sheet

    def _select_rows(self, train_type: str, case: int, stop_error_m: float) -> List[MovementRow]:
        candidates = [
            row for row in self.repo.get_rows_for_train(train_type)
            if row.case == case and row.valid.upper() == "OK"
        ]
        if not candidates:
            return []

        exact = [
            row for row in candidates
            if abs(row.stop_error_m - stop_error_m) <= STOP_ERROR_MATCH_TOL_M
        ]
        if exact:
            return exact

        # exact matching 실패 시 가장 가까운 stop_error 군을 사용
        nearest_gap = min(abs(row.stop_error_m - stop_error_m) for row in candidates)
        if nearest_gap > STOP_ERROR_FALLBACK_MAX_GAP_M:
            return []

        return [
            row for row in candidates
            if abs(row.stop_error_m - stop_error_m) == nearest_gap
        ]

    def build_open_payload(self, train_type: str, case: int, stop_error_m: float, seq: int) -> Tuple[dict, List[int]]:
        rows = self._select_rows(train_type, case, stop_error_m)
        if not rows:
            raise ValueError(
                f"Movement_Data 에서 매칭 실패: train_type={train_type}, case={case}, stop_error_m={stop_error_m}"
            )

        merged: Dict[int, DoorCommand] = {}

        for row in rows:
            normalized_dir = self._normalize_dir(row.direction, row.move_distance_m)
            dist_step = self._distance_m_to_step(row.move_distance_m)
            if normalized_dir == "None" or dist_step == 0:
                continue

            start_unit = min(row.open_unit_start, row.open_unit_end)
            end_unit = max(row.open_unit_start, row.open_unit_end)

            for unit_id in range(start_unit, end_unit + 1):
                dcu_idx = self._sheet_unit_to_dcu_idx(unit_id)
                if dcu_idx < DOOR_ID_MIN or dcu_idx > DOOR_ID_MAX:
                    continue

                prev = merged.get(dcu_idx)
                if prev is None:
                    merged[dcu_idx] = DoorCommand(
                        dcu_idx=dcu_idx,
                        cmd="Open",
                        dir=normalized_dir,
                        dist_step=dist_step,
                    )
                else:
                    prev.dir = self._merge_dir(prev.dir, normalized_dir)
                    prev.dist_step = max(prev.dist_step, dist_step)

        doors = [
            {
                "dcu_idx": cmd.dcu_idx,
                "cmd": cmd.cmd,
                "dir": cmd.dir,
                "dist_step": cmd.dist_step,
            }
            for cmd in sorted(merged.values(), key=lambda x: x.dcu_idx)
        ]
        if not doors:
            raise ValueError("유효한 문 제어 명령이 생성되지 않았습니다.")

        payload = {
            "platform_id": self.platform_id,
            "seq": seq,
            "doors": doors,
        }
        if USE_CRC_PLACEHOLDER:
            payload["crc"] = CRC_PLACEHOLDER

        active_doors = [item["dcu_idx"] for item in doors]
        return payload, active_doors

    def build_close_payload(self, active_doors: List[int], seq: int) -> dict:
        doors = [
            {"dcu_idx": dcu_idx, "cmd": "Close", "dir": "Both", "dist_step": 8}
            for dcu_idx in sorted(set(active_doors))
        ]
        payload = {"platform_id": self.platform_id, "seq": seq, "doors": doors}
        if USE_CRC_PLACEHOLDER:
            payload["crc"] = CRC_PLACEHOLDER
        return payload

    def build_stop_payload(self, seq: int, target_doors: Optional[List[int]] = None) -> dict:
        door_ids = target_doors if target_doors else list(range(DOOR_ID_MIN, DOOR_ID_MAX + 1))
        doors = [
            {"dcu_idx": dcu_idx, "cmd": "Stop", "dir": "None", "dist_step": 0}
            for dcu_idx in sorted(set(door_ids))
        ]
        payload = {"platform_id": self.platform_id, "seq": seq, "doors": doors}
        if USE_CRC_PLACEHOLDER:
            payload["crc"] = CRC_PLACEHOLDER
        return payload
