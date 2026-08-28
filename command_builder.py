from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from config import (
    DIST_STEP_MAX,
    DIST_STEP_WIDTH_M,
    DOOR_ID_MAX,
    DOOR_ID_MIN,
    STOP_ERROR_FALLBACK_MAX_GAP_M,
    STOP_ERROR_MATCH_TOL_M,
)
from data_loader import AUSDLookupRepository, AUSDLookupRow


@dataclass
class DoorSelection:
    dcu_idx: int
    dir: str
    open_dist_step: int


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
        # AUSD CSV의 Unit ID가 이미 New JSON dcu_idx입니다.
        return unit_id_from_lookup

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

    def build_train_context_payload(
        self,
        train_type: str,
        case: int,
        stop_error_m: float,
        seq: int,
    ) -> Tuple[dict, Dict[int, DoorSelection]]:
        """신형 JSON의 train_context 문 지정 요청을 생성합니다."""
        rows = self._select_rows(train_type, case, stop_error_m)
        if not rows:
            raise ValueError(
                f"AUSD 룩업 매칭 실패: train_type={train_type}, case={case}, "
                f"stop_error_m={stop_error_m}"
            )

        selected: Dict[int, DoorSelection] = {}
        ignored_dcu_idxs = set()

        for row in rows:
            normalized_dir = self._normalize_dir(row.direction, row.move_distance_m)
            open_dist_step = self._distance_m_to_step(row.move_distance_m)

            if normalized_dir == "None" or open_dist_step == 0:
                continue

            dcu_idx = self._unit_to_dcu_idx(row.unit_id)
            if dcu_idx < DOOR_ID_MIN or dcu_idx > DOOR_ID_MAX:
                ignored_dcu_idxs.add(dcu_idx)
                continue

            previous = selected.get(dcu_idx)
            if previous is None:
                selected[dcu_idx] = DoorSelection(
                    dcu_idx=dcu_idx,
                    dir=normalized_dir,
                    open_dist_step=open_dist_step,
                )
                continue

            if previous.dir != normalized_dir:
                raise ValueError(
                    f"Conflicting directions for dcu_idx={dcu_idx}: "
                    f"{previous.dir} vs {normalized_dir}"
                )
            previous.open_dist_step = max(previous.open_dist_step, open_dist_step)

        if ignored_dcu_idxs:
            print(
                f"[WARN] New JSON dcu_idx 범위 {DOOR_ID_MIN}~{DOOR_ID_MAX}를 "
                f"벗어난 문을 무시했습니다: {sorted(ignored_dcu_idxs)}"
            )

        if not selected:
            raise ValueError("유효한 train_context 문 지정이 생성되지 않았습니다.")

        payload = {
            "msg_type": "train_context",
            "platform_id": self.platform_id,
            "seq": seq,
            "train_present": True,
            "case": case,
            "doors": [
                {
                    "dcu_idx": selection.dcu_idx,
                    "dir": selection.dir,
                    "open_dist_step": selection.open_dist_step,
                }
                for selection in sorted(
                    selected.values(), key=lambda item: item.dcu_idx
                )
            ],
        }
        return payload, selected

    def build_train_absent_payload(self, seq: int) -> dict:
        return {
            "msg_type": "train_context",
            "platform_id": self.platform_id,
            "seq": seq,
            "train_present": False,
        }

    def build_door_control_payload(self, action: str, seq: int) -> dict:
        normalized_action = (action or "").strip().lower()
        if normalized_action not in {"open", "close", "stop"}:
            raise ValueError(f"지원하지 않는 door_control action: {action}")

        return {
            "msg_type": "door_control",
            "platform_id": self.platform_id,
            "seq": seq,
            "action": normalized_action,
        }

    def build_emergency_control_payload(self, action: str, seq: int) -> dict:
        normalized_action = (action or "").strip().lower()
        if normalized_action not in {"enter", "release"}:
            raise ValueError(f"지원하지 않는 emergency_control action: {action}")

        return {
            "msg_type": "emergency_control",
            "platform_id": self.platform_id,
            "seq": seq,
            "action": normalized_action,
        }

    def build_status_request_payload(self, scope: str, seq: int) -> dict:
        normalized_scope = (scope or "").strip().lower()
        if normalized_scope not in {"active", "all"}:
            raise ValueError(f"status_request scope는 active 또는 all이어야 합니다: {scope}")

        return {
            "msg_type": "status_request",
            "platform_id": self.platform_id,
            "seq": seq,
            "scope": normalized_scope,
        }
