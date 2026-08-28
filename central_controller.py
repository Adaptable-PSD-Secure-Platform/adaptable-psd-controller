from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from command_builder import CommandBuilder, DoorSelection
from data_loader import AUSDLookupRepository


class TransportProtocol(Protocol):
    def send_json(self, payload: dict) -> None:
        ...


@dataclass
class OperatorState:
    train_type: Optional[str] = None
    case: Optional[int] = None
    # AUSD 룩업의 Stop Error 매칭용 입력값입니다. New JSON에는 직접 전송하지 않습니다.
    stop_error_m: Optional[float] = None
    train_present: Optional[bool] = None
    train_state: Optional[str] = None
    position_valid: Optional[bool] = None
    platform_status: Optional[str] = None
    initialized: Optional[bool] = None
    selection_valid: Optional[bool] = None
    doors_status: List[Dict[str, Any]] = field(default_factory=list)
    emergency: bool = False


class CentralController:
    def __init__(
        self,
        platform_id: int,
        repo: AUSDLookupRepository,
        transport: TransportProtocol,
    ) -> None:
        self.platform_id = platform_id
        self.repo = repo
        self.transport = transport
        self.builder = CommandBuilder(repo=self.repo, platform_id=self.platform_id)

        self.state = OperatorState()

        # New JSON 규격은 seq=1부터 단조 증가시킵니다.
        self.seq = 0

        # train_context 승인 전/후의 문 지정 정보를 분리해 보관합니다.
        self.pending_selection: Dict[int, DoorSelection] = {}
        self.selected_doors: Dict[int, DoorSelection] = {}

        self.last_ack: Optional[Dict[str, Any]] = None
        self.last_selection_ack: Optional[Dict[str, Any]] = None
        self.last_control_ack: Optional[Dict[str, Any]] = None
        self.last_status_ack: Optional[Dict[str, Any]] = None
        self.last_emergency_status: Optional[Dict[str, Any]] = None

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def reset_seq(self) -> None:
        self.seq = 0
        print("[CTRL] seq reset requested. Next request will use seq=1")

    def reset_state(self) -> None:
        self.state = OperatorState()
        self.pending_selection.clear()
        self.selected_doors.clear()
        self.last_ack = None
        self.last_selection_ack = None
        self.last_control_ack = None
        self.last_status_ack = None
        self.last_emergency_status = None
        print("[CTRL] controller state reset")

    # ---------- 입력 업데이트 ----------
    def update_train_type(self, train_type: str) -> None:
        self.state.train_type = train_type.strip()
        print(f"[CTRL] train_type={self.state.train_type}")

    def update_stop_context(self, case: int, stop_error_m: float) -> None:
        self.state.case = case
        self.state.stop_error_m = stop_error_m
        # 수동 입력은 status_request를 대신하는 운용자 fallback입니다.
        self.state.train_present = True
        self.state.train_state = "STOPPED"
        self.state.position_valid = True
        print(f"[CTRL] case={case}, stop_error_m={stop_error_m}")

    def update_from_status_ack(self, msg: Dict[str, Any]) -> None:
        self.state.platform_status = msg.get("status")
        if self.state.platform_status is not None:
            self.state.emergency = str(self.state.platform_status) == "EMERGENCY"
        self.state.initialized = msg.get("initialized")
        self.state.selection_valid = msg.get("selection_valid")

        train_state = msg.get("train_state")
        if train_state is not None:
            self.state.train_state = str(train_state)
            self.state.train_present = self.state.train_state != "EMPTY"

        if "position_valid" in msg:
            self.state.position_valid = bool(msg["position_valid"])

        if "case" in msg and msg["case"] not in (None, ""):
            try:
                self.state.case = int(msg["case"])
            except (TypeError, ValueError):
                print(f"[CTRL] invalid case in status_ack: {msg.get('case')}")

        doors_status = msg.get("doors_status")
        if isinstance(doors_status, list):
            self.state.doors_status = doors_status

        if self.state.platform_status == "EMERGENCY":
            self.state.emergency = True

    def set_emergency(self, value: bool) -> None:
        if self.state.emergency == value:
            print(f"[CTRL] emergency already {'on' if value else 'off'}")
            return

        action = "enter" if value else "release"
        payload = self.builder.build_emergency_control_payload(
            action=action,
            seq=self.next_seq(),
        )
        self.transport.send_json(payload)
        self.state.emergency = value
        print(f"[CTRL] emergency_control sent, action={action}")

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

        if s.train_present is False or s.train_state != "STOPPED" or s.position_valid is not True:
            print("[BLOCK] train_state=STOPPED 및 position_valid=true 상태가 필요합니다.")
            return False

        return True

    def can_control_selected_doors(self) -> bool:
        if self.state.emergency:
            print("[BLOCK] emergency 상태입니다.")
            return False

        if not self.selected_doors:
            print("[BLOCK] 승인된 문 지정 정보가 없습니다.")
            return False

        if self.state.selection_valid is not True:
            print("[BLOCK] selection_ack 승인 상태가 아닙니다.")
            return False

        return True

    # ---------- New JSON 요청 ----------
    def send_open(self) -> None:
        if not self.can_open():
            return

        payload, selection = self.builder.build_train_context_payload(
            train_type=self.state.train_type,
            case=self.state.case,
            stop_error_m=self.state.stop_error_m,
            seq=self.next_seq(),
        )

        # ACK가 즉시 도착하는 Mock에서도 선택 정보가 먼저 존재해야 합니다.
        self.pending_selection = selection
        self.state.selection_valid = False
        self.transport.send_json(payload)
        print(f"[CTRL] train_context sent, selected_doors={sorted(selection.keys())}")

    def send_close(self) -> None:
        if not self.can_control_selected_doors():
            return
        self._send_door_control("close")

    def send_stop(self) -> None:
        if not self.can_control_selected_doors():
            return
        self._send_door_control("stop")

    def send_train_absent(self) -> None:
        payload = self.builder.build_train_absent_payload(seq=self.next_seq())
        self.transport.send_json(payload)
        self.pending_selection.clear()
        self.selected_doors.clear()
        self.state.train_present = False
        self.state.train_state = "EMPTY"
        self.state.selection_valid = False
        print("[CTRL] train_context sent, train_present=false")

    def request_status(self, scope: str = "all") -> None:
        payload = self.builder.build_status_request_payload(
            scope=scope,
            seq=self.next_seq(),
        )
        self.transport.send_json(payload)
        print(f"[CTRL] status_request sent, scope={scope}")

    def _send_door_control(self, action: str) -> None:
        payload = self.builder.build_door_control_payload(
            action=action,
            seq=self.next_seq(),
        )
        self.transport.send_json(payload)
        print(f"[CTRL] door_control sent, action={action}")

    # ---------- ESP32 ACK 및 상태 처리 ----------
    def handle_feedback(self, msg: Dict[str, Any]) -> None:
        if not isinstance(msg, dict):
            print(f"[UNKNOWN FEEDBACK] {msg}")
            return

        if msg.get("platform_id") != self.platform_id:
            print(f"[WARN] feedback platform_id mismatch: {msg}")
            return

        msg_type = msg.get("msg_type")

        if msg_type == "selection_ack":
            self.last_selection_ack = msg
            print(f"[SELECTION_ACK] {msg}")

            if str(msg.get("result", "")).upper() != "OK":
                self.pending_selection.clear()
                self.selected_doors.clear()
                self.state.selection_valid = False
                return

            self.state.selection_valid = True
            if self.pending_selection:
                self.selected_doors = self.pending_selection
                self.pending_selection = {}
                # 문 지정 ACK 이후에만 실제 OPEN 요청을 전송합니다.
                self._send_door_control("open")
            else:
                self.selected_doors.clear()
                self.state.selection_valid = int(msg.get("selected_count", 0) or 0) > 0
            return

        if msg_type == "control_ack":
            self.last_control_ack = msg
            command = str(msg.get("command", "")).upper()
            if str(msg.get("result", "")).upper() == "OK":
                if command == "EMERGENCY":
                    self.state.emergency = True
                elif command == "RECOVERY":
                    self.state.emergency = False
                if msg.get("status") is not None:
                    self.state.platform_status = str(msg["status"])
            print(f"[CONTROL_ACK] {msg}")
            return

        if msg_type == "status_ack":
            self.last_status_ack = msg
            self.update_from_status_ack(msg)
            print(f"[STATUS_ACK] {msg}")
            return

        if msg_type == "emergency_status":
            self.last_emergency_status = msg
            self.state.emergency = bool(msg.get("active", False))
            if msg.get("status") is not None:
                self.state.platform_status = str(msg["status"])
            print(f"[EMERGENCY_STATUS] {msg}")
            return

        if msg_type == "ack":
            self.last_ack = msg
            print(f"[ACK] {msg}")
            return

        print(f"[UNKNOWN FEEDBACK] {msg}")

    # ---------- 상태 출력 ----------
    def print_state(self) -> None:
        print("\n========== CENTRAL CONTROLLER STATE ==========")
        print(self.state)
        print(f"next_seq_will_be={self.seq + 1}")
        print(f"selected_doors={sorted(self.selected_doors.keys())}")
        print(f"pending_selection={sorted(self.pending_selection.keys())}")
        print(f"last_ack={self.last_ack}")
        print(f"last_selection_ack={self.last_selection_ack}")
        print(f"last_control_ack={self.last_control_ack}")
        print(f"last_status_ack={self.last_status_ack}")
        print(f"last_emergency_status={self.last_emergency_status}")
        print("==============================================\n")
