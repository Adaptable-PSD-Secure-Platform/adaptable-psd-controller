from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from command_builder import CommandBuilder
from data_loader import MovementDataRepository


class TransportProtocol(Protocol):
    def send_json(self, payload: dict) -> None:
        ...


@dataclass
class OperatorState:
    train_type: Optional[str] = None
    case: Optional[int] = None
    stop_error_m: Optional[float] = None
    stopped: bool = False
    open_approved: bool = False
    close_approved: bool = False
    emergency: bool = False


class CentralController:
    def __init__(
        self,
        platform_id: int,
        repo: MovementDataRepository,
        transport: TransportProtocol,
    ) -> None:
        self.platform_id = platform_id
        self.repo = repo
        self.transport = transport
        self.builder = CommandBuilder(repo=self.repo, platform_id=self.platform_id)

        self.state = OperatorState()
        self.seq = 0
        self.active_doors: List[int] = []

        self.last_ack: Optional[Dict[str, Any]] = None
        self.last_sensor: Optional[Dict[str, Any]] = None

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    # ---------- 입력 업데이트 ----------
    def update_train_type(self, train_type: str) -> None:
        self.state.train_type = train_type
        print(f"[CTRL] train_type={train_type}")

    def update_stop_context(self, case: int, stop_error_m: float) -> None:
        self.state.case = case
        self.state.stop_error_m = stop_error_m
        print(f"[CTRL] case={case}, stop_error_m={stop_error_m}")

    def set_stopped(self, value: bool) -> None:
        self.state.stopped = value
        print(f"[CTRL] stopped={value}")

    def set_open_approved(self, value: bool) -> None:
        self.state.open_approved = value
        print(f"[CTRL] open_approved={value}")

    def set_close_approved(self, value: bool) -> None:
        self.state.close_approved = value
        print(f"[CTRL] close_approved={value}")

    def set_emergency(self, value: bool) -> None:
        self.state.emergency = value
        print(f"[CTRL] emergency={value}")

        if value:
            self.send_stop(all_doors=True)

    # ---------- 제어 조건 검사 ----------
    def can_open(self) -> bool:
        s = self.state

        if s.emergency:
            print("[BLOCK] emergency 상태입니다.")
            return False

        if not s.train_type:
            print("[BLOCK] train_type 이 없습니다.")
            return False

        if s.case is None or s.stop_error_m is None:
            print("[BLOCK] case / stop_error_m 이 없습니다.")
            return False

        if not s.stopped:
            print("[BLOCK] stopped=False 입니다.")
            return False

        if not s.open_approved:
            print("[BLOCK] open_approved=False 입니다.")
            return False

        return True

    def can_close(self) -> bool:
        if self.state.emergency:
            print("[BLOCK] emergency 상태입니다.")
            return False

        if not self.state.close_approved:
            print("[BLOCK] close_approved=False 입니다.")
            return False

        if not self.active_doors:
            print("[BLOCK] active_doors 가 비어 있습니다.")
            return False

        return True

    # ---------- 제어 명령 ----------
    def send_open(self) -> None:
        if not self.can_open():
            return

        payload, active_doors = self.builder.build_open_payload(
            train_type=self.state.train_type,
            case=self.state.case,
            stop_error_m=self.state.stop_error_m,
            seq=self.next_seq(),
        )

        self.transport.send_json(payload)
        self.active_doors = active_doors
        print(f"[CTRL] OPEN sent, active_doors={self.active_doors}")

    def send_close(self) -> None:
        if not self.can_close():
            return

        payload = self.builder.build_close_payload(
            active_doors=self.active_doors,
            seq=self.next_seq(),
        )

        self.transport.send_json(payload)
        print(f"[CTRL] CLOSE sent, active_doors={self.active_doors}")

    def send_stop(self, all_doors: bool = False) -> None:
        target = None if all_doors else self.active_doors

        payload = self.builder.build_stop_payload(
            seq=self.next_seq(),
            target_doors=target,
        )

        self.transport.send_json(payload)

        if all_doors:
            print("[CTRL] STOP ALL sent")
        else:
            print(f"[CTRL] STOP sent, target={target}")

    # ---------- ESP32 피드백 처리 ----------
    def handle_feedback(self, msg: Dict[str, Any]) -> None:
        if "result" in msg:
            self.last_ack = msg
            print(f"[ACK] {msg}")
            return

        if "doors_status" in msg or "status" in msg:
            self.last_sensor = msg
            print(f"[SENSOR] {msg}")
            return

        print(f"[UNKNOWN FEEDBACK] {msg}")

    # ---------- 상태 출력 ----------
    def print_state(self) -> None:
        print("\n========== CENTRAL CONTROLLER STATE ==========")
        print(self.state)
        print(f"seq={self.seq}")
        print(f"active_doors={self.active_doors}")
        print(f"last_ack={self.last_ack}")
        print(f"last_sensor={self.last_sensor}")
        print("==============================================\n")