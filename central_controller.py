from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from command_builder import CommandBuilder, DoorCommand
from data_loader import MovementDataRepository


class TransportProtocol(Protocol):
    def send_json(self, payload: dict) -> None:
        ...


@dataclass
class OperatorState:
    train_type: Optional[str] = None
    case: Optional[int] = None
    stop_error_m: Optional[float] = None
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

        # 첫 명령이 seq=0 이 되도록 시작값 -1
        self.seq = -1

        # 마지막 OPEN 명령 정보를 보관해 CLOSE 시 재사용
        self.active_commands: Dict[int, DoorCommand] = {}

        self.last_ack: Optional[Dict[str, Any]] = None
        self.last_status_report: Optional[Dict[str, Any]] = None

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def reset_seq(self) -> None:
        self.seq = -1
        print("[CTRL] seq reset requested. Next command will use seq=0")

    def reset_state(self) -> None:
        self.state = OperatorState()
        self.active_commands.clear()
        self.last_ack = None
        self.last_status_report = None
        print("[CTRL] controller state reset")

    # ---------- 입력 업데이트 ----------
    def update_train_type(self, train_type: str) -> None:
        self.state.train_type = train_type
        print(f"[CTRL] train_type={train_type}")

    def update_stop_context(self, case: int, stop_error_m: float) -> None:
        self.state.case = case
        self.state.stop_error_m = stop_error_m
        print(f"[CTRL] case={case}, stop_error_m={stop_error_m}")

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

        return True

    def can_close(self) -> bool:
        if self.state.emergency:
            print("[BLOCK] emergency 상태입니다.")
            return False

        if not self.active_commands:
            print("[BLOCK] active_commands 가 비어 있습니다.")
            return False

        return True

    # ---------- 제어 명령 ----------
    def send_open(self) -> None:
        if not self.can_open():
            return

        payload, active_commands = self.builder.build_open_payload(
            train_type=self.state.train_type,
            case=self.state.case,
            stop_error_m=self.state.stop_error_m,
            seq=self.next_seq(),
        )

        self.transport.send_json(payload)
        self.active_commands = active_commands
        print(f"[CTRL] OPEN sent, active_doors={sorted(self.active_commands.keys())}")

    def send_close(self) -> None:
        if not self.can_close():
            return

        payload = self.builder.build_close_payload(
            active_commands=self.active_commands,
            seq=self.next_seq(),
        )
        self.transport.send_json(payload)
        print(f"[CTRL] CLOSE sent, active_doors={sorted(self.active_commands.keys())}")

    def send_stop(self, all_doors: bool = False) -> None:
        target = None if all_doors else list(self.active_commands.keys())
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
        msg_type = msg.get("msg_type")

        if msg_type == "ack":
            if msg.get("platform_id") != self.platform_id:
                print(f"[WARN] ACK platform_id mismatch: {msg}")
                return
            self.last_ack = msg
            print(f"[ACK] {msg}")
            return

        if msg_type == "status_report":
            if msg.get("platform_id") != self.platform_id:
                print(f"[WARN] STATUS platform_id mismatch: {msg}")
                return
            self.last_status_report = msg
            print(f"[STATUS_REPORT] {msg}")
            return

        # 하위 호환
        if "result" in msg:
            self.last_ack = msg
            print(f"[ACK-LEGACY] {msg}")
            return

        if "doors_status" in msg and "status" in msg:
            self.last_status_report = msg
            print(f"[STATUS_REPORT-LEGACY] {msg}")
            return

        print(f"[UNKNOWN FEEDBACK] {msg}")

    # ---------- 상태 출력 ----------
    def print_state(self) -> None:
        print("\n========== CENTRAL CONTROLLER STATE ==========")
        print(self.state)
        print(f"next_seq_will_be={self.seq + 1}")
        print(f"active_doors={sorted(self.active_commands.keys())}")
        print(f"last_ack={self.last_ack}")
        print(f"last_status_report={self.last_status_report}")
        print("==============================================\n")