from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from config import (
    DIST_STEP_MAX,
    DIST_STEP_WIDTH_M,
    DOOR_ID_MAX,
    DOOR_ID_MIN,
    AUSD_UNIT_ID_IS_1_BASED,
    STOP_ERROR_FALLBACK_MAX_GAP_M,
    STOP_ERROR_MATCH_TOL_M,
)
from data_loader import AUSDLookupRepository, AUSDLookupRow


@dataclass
class DoorCommand:
    dcu_idx: int
    cmd: str
    dir: str
    dist_step: int


class CommandBuilder:
    def __init__(self, repo: AUSDLookupRepository, platform_id: int) -> None:
        self.repo = repo
        self.platform_id = platform_id

    @staticmethod
    def _normalize_dir(direction: str, move_distance_m: float) -> str:
        d = (direction or "").strip().lower()

        # PDF 주의사항: Both 는 허용하지 않음
        if d == "both":
            raise ValueError("Protocol does not allow 'Both'. Only Left/Right/None are allowed.")

        if d == "left":
            return "Left"
        if d == "right":
            return "Right"
        if d == "none":
            return "None"

        # direction 문자열이 비어 있으면 거리 부호로 보정
        if move_distance_m < 0:
            return "Left"
        if move_distance_m > 0:
            return "Right"
        return "None"

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
    def _unit_to_dcu_idx(unit_id_from_lookup: int) -> int:
        return unit_id_from_lookup - 1 if AUSD_UNIT_ID_IS_1_BASED else unit_id_from_lookup

    def _select_rows(self, train_type: str, case: int, stop_error_m: float) -> List[AUSDLookupRow]:
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

        nearest_gap = min(abs(row.stop_error_m - stop_error_m) for row in candidates)
        if nearest_gap > STOP_ERROR_FALLBACK_MAX_GAP_M:
            return []

        return [
            row for row in candidates
            if abs(row.stop_error_m - stop_error_m) == nearest_gap
        ]

    def build_open_payload(
        self,
        train_type: str,
        case: int,
        stop_error_m: float,
        seq: int,
    ) -> Tuple[dict, Dict[int, DoorCommand]]:
        rows = self._select_rows(train_type, case, stop_error_m)
        if not rows:
            raise ValueError(
                f"AUSD 룩업 매칭 실패: train_type={train_type}, case={case}, "
                f"stop_error_m={stop_error_m}"
            )

        merged: Dict[int, DoorCommand] = {}

        for row in rows:
            normalized_dir = self._normalize_dir(row.direction, row.move_distance_m)
            dist_step = self._distance_m_to_step(row.move_distance_m)

            if normalized_dir == "None" or dist_step == 0:
                continue

            dcu_idx = self._unit_to_dcu_idx(row.unit_id)
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
                # 최종 프로토콜상 Both 금지 → 같은 dcu_idx 에 서로 반대 방향이 오면 상위 계산/시트 문제로 보고 실패
                if prev.dir != normalized_dir:
                    raise ValueError(
                        f"Conflicting directions for dcu_idx={dcu_idx}: {prev.dir} vs {normalized_dir}. "
                        f"'Both' is not allowed by the finalized protocol."
                    )
                prev.dist_step = max(prev.dist_step, dist_step)

        doors = [
            {
                "dcu_idx": cmd.dcu_idx,
                "cmd": "Open",
                "dir": cmd.dir,
                "dist_step": cmd.dist_step,
            }
            for cmd in sorted(merged.values(), key=lambda x: x.dcu_idx)
        ]
        if not doors:
            raise ValueError("유효한 OPEN 명령이 생성되지 않았습니다.")

        payload = {
            "platform_id": self.platform_id,
            "seq": seq,
            "doors": doors,
        }
        return payload, merged

    def build_close_payload(self, active_commands: Dict[int, DoorCommand], seq: int) -> dict:
        if not active_commands:
            raise ValueError("닫을 active_commands 가 없습니다.")

        doors = [
            {
                "dcu_idx": cmd.dcu_idx,
                "cmd": "Close",
                # PDF 4.1: Close 도 Left/Right/None 만 허용, None 금지 → 직전 open 방향 유지
                "dir": cmd.dir,
                "dist_step": DIST_STEP_MAX,
            }
            for cmd in sorted(active_commands.values(), key=lambda x: x.dcu_idx)
        ]
        return {
            "platform_id": self.platform_id,
            "seq": seq,
            "doors": doors,
        }

    def build_stop_payload(self, seq: int, target_doors: Optional[List[int]] = None) -> dict:
        door_ids = (
            target_doors
            if target_doors is not None
            else list(range(DOOR_ID_MIN, DOOR_ID_MAX + 1))
        )
        doors = [
            {
                "dcu_idx": dcu_idx,
                "cmd": "Stop",
                "dir": "None",
                "dist_step": 0,
            }
            for dcu_idx in sorted(set(door_ids))
        ]
        return {
            "platform_id": self.platform_id,
            "seq": seq,
            "doors": doors,
        }
