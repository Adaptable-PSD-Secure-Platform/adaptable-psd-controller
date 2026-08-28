from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from command_builder import CommandBuilder, DoorSelection
from config import DEFAULT_STOP_ERROR_M
from data_loader import AUSDLookupRepository


class TransportProtocol(Protocol):
    def send_json(self, payload: dict) -> None:
        ...


StateListener = Callable[[Dict[str, Any]], None]


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
        self._selection_context_key: Optional[Tuple[str, int, float]] = None
        self._status_gate_approved = False

        self.last_ack: Optional[Dict[str, Any]] = None
        self.last_selection_ack: Optional[Dict[str, Any]] = None
        self.last_control_ack: Optional[Dict[str, Any]] = None
        self.last_status_ack: Optional[Dict[str, Any]] = None
        self.last_emergency_status: Optional[Dict[str, Any]] = None
        self._state_listeners: List[StateListener] = []

    def add_state_listener(self, listener: StateListener) -> None:
        """HTML 시뮬레이터 등 상태 구독자를 추가합니다."""
        if listener not in self._state_listeners:
            self._state_listeners.append(listener)

    def get_visualization_snapshot(self, event: str = "state_snapshot") -> Dict[str, Any]:
        """ESP32 원본 메시지와 분리된 HTML용 현재 상태를 반환합니다."""
        def serialize_selection(selection: DoorSelection) -> Dict[str, Any]:
            return {
                "dcu_idx": selection.dcu_idx,
                "dir": selection.dir,
                "open_dist_step": selection.open_dist_step,
            }

        return {
            "type": "state_snapshot",
            "event": event,
            "platform_id": self.platform_id,
            "controller_seq": self.seq,
            "train_type": self.state.train_type,
            "case": self.state.case,
            "stop_error_m": self.state.stop_error_m,
            "train_present": self.state.train_present,
            "train_state": self.state.train_state,
            "position_valid": self.state.position_valid,
            "status_gate_approved": self._status_gate_approved,
            "platform_status": self.state.platform_status,
            "initialized": self.state.initialized,
            "selection_valid": self.state.selection_valid,
            "emergency": self.state.emergency,
            "pending_doors": [
                serialize_selection(selection)
                for selection in sorted(
                    self.pending_selection.values(),
                    key=lambda item: item.dcu_idx,
                )
            ],
            "selected_doors": [
                serialize_selection(selection)
                for selection in sorted(
                    self.selected_doors.values(),
                    key=lambda item: item.dcu_idx,
                )
            ],
            "doors": [dict(status) for status in self.state.doors_status],
        }

    def _notify_state(self, event: str) -> None:
        snapshot = self.get_visualization_snapshot(event=event)
        for listener in list(self._state_listeners):
            try:
                listener(snapshot)
            except Exception as exc:
                print(f"[HTML] state listener error: {exc}")

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
        self._selection_context_key = None
        self._status_gate_approved = False
        self.last_ack = None
        self.last_selection_ack = None
        self.last_control_ack = None
        self.last_status_ack = None
        self.last_emergency_status = None
        print("[CTRL] controller state reset")
        self._notify_state("reset")

    # ---------- 입력 업데이트 ----------
    def update_train_type(self, train_type: str) -> None:
        normalized_train_type = train_type.strip()
        if normalized_train_type != self.state.train_type:
            self.pending_selection.clear()
            self.selected_doors.clear()
            self._selection_context_key = None
            self.state.selection_valid = False
            # 새 열차 종류가 감지되면 이전 열차의 status_ack 승인도 폐기합니다.
            # 새 status_request/status_ack를 받은 뒤에만 문 지정을 허용합니다.
            self._status_gate_approved = False
            self.state.case = None
            self.state.stop_error_m = None
        self.state.train_type = normalized_train_type
        print(f"[CTRL] train_type={self.state.train_type}")
        self._notify_state("train_type_updated")

    def update_stop_context(self, case: int, stop_error_m: float) -> None:
        # 수동 입력은 상태 응답을 대체하지 않습니다. 실제 train_context 전송은
        # ESP32 status_ack에서 STOPPED + position_valid=true를 받은 뒤에만 허용합니다.
        self._status_gate_approved = False
        if self.state.case != case or self.state.stop_error_m != stop_error_m:
            self.pending_selection.clear()
            self.selected_doors.clear()
            self._selection_context_key = None
            self.state.selection_valid = False
        self.state.case = case
        self.state.stop_error_m = stop_error_m
        # 수동 입력은 status_request를 대신하는 운용자 fallback입니다.
        self.state.train_present = True
        self.state.train_state = "STOPPED"
        self.state.position_valid = True
        print(f"[CTRL] case={case}, stop_error_m={stop_error_m}")
        self._notify_state("stop_context_updated")

    def update_from_status_ack(self, msg: Dict[str, Any]) -> None:
        previous_case = self.state.case
        previous_train_state = self.state.train_state
        if str(msg.get("result", "OK")).upper() != "OK":
            self._status_gate_approved = False
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

        # 문서상 status_ack에는 stop_error가 없지만, 확장 응답이 들어오면
        # 내부 룩업 매칭에만 사용합니다. New JSON으로는 전송하지 않습니다.
        if "stop_error_m" in msg:
            try:
                self.state.stop_error_m = float(msg["stop_error_m"])
            except (TypeError, ValueError):
                print(f"[CTRL] invalid stop_error_m in status_ack: {msg.get('stop_error_m')}")
        elif "stop_error_mm" in msg:
            try:
                self.state.stop_error_m = float(msg["stop_error_mm"]) / 1000.0
            except (TypeError, ValueError):
                print(f"[CTRL] invalid stop_error_mm in status_ack: {msg.get('stop_error_mm')}")

        doors_status = msg.get("doors_status")
        if isinstance(doors_status, list):
            self.state.doors_status = doors_status

        if self.state.platform_status == "EMERGENCY":
            self.state.emergency = True

        if self.state.case != previous_case or (
            previous_train_state == "EMPTY" and self.state.train_state != "EMPTY"
        ):
            self.pending_selection.clear()
            self.selected_doors.clear()
            self._selection_context_key = None
            self.state.selection_valid = False

        if self.state.train_state == "EMPTY":
            self.pending_selection.clear()
            self.selected_doors.clear()
            self._selection_context_key = None
            self.state.selection_valid = False

        self._status_gate_approved = (
            str(msg.get("result", "OK")).upper() == "OK"
            and self.state.train_state == "STOPPED"
            and self.state.position_valid is True
            and self.state.case is not None
            and self.state.train_present is not False
        )
        if not self._status_gate_approved:
            self.pending_selection.clear()
            self.selected_doors.clear()
            self._selection_context_key = None
            self.state.selection_valid = False

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
        self._notify_state("emergency_command_sent")
        print(f"[CTRL] emergency_control sent, action={action}")

    # ---------- 제어 조건 검사 ----------
    def can_send_train_context(self) -> bool:
        s = self.state

        if s.emergency:
            print("[BLOCK] emergency 상태입니다.")
            return False

        if not s.train_type:
            print("[BLOCK] train_type 이 없습니다.")
            return False

        if s.case is None:
            print("[BLOCK] status_ack의 case가 없습니다.")
            return False

        if not self._status_gate_approved:
            print("[BLOCK] ESP32 status_ack에서 train_state=STOPPED 및 position_valid=true 확인이 필요합니다.")
            return False

        return True

    def can_open(self) -> bool:
        return self.can_control_selected_doors()

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
    def send_train_context(self) -> None:
        """현재 정차 상태에 대한 문 지정만 전송합니다."""
        if not self.can_send_train_context():
            return

        if self.pending_selection:
            print("[BLOCK] train_context 승인 응답을 기다리는 중입니다.")
            return

        if self.selected_doors and self.state.selection_valid is True:
            print("[INFO] 이미 승인된 train_context가 있습니다. open 명령을 사용하세요.")
            return

        self._send_train_context()

    def _send_train_context(self) -> None:
        stop_error_m = (
            self.state.stop_error_m
            if self.state.stop_error_m is not None
            else DEFAULT_STOP_ERROR_M
        )

        payload, selection = self.builder.build_train_context_payload(
            train_type=self.state.train_type,
            case=self.state.case,
            stop_error_m=stop_error_m,
            seq=self.next_seq(),
        )

        # ACK가 즉시 도착하는 Mock에서도 선택 정보가 먼저 존재해야 합니다.
        self.pending_selection = selection
        self._selection_context_key = (
            self.state.train_type or "",
            int(self.state.case),
            round(float(stop_error_m), 6),
        )
        self.state.selection_valid = False
        self._notify_state("train_context_sent")
        self.transport.send_json(payload)
        print(f"[CTRL] train_context sent, selected_doors={sorted(selection.keys())}")

    def send_open(self) -> None:
        """직전에 selection_ack로 승인된 train_context에 OPEN을 적용합니다."""
        if not self.can_open():
            return
        self._send_door_control("open")

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
        self._selection_context_key = None
        self._status_gate_approved = False
        self.state.train_present = False
        self.state.train_state = "EMPTY"
        self.state.selection_valid = False
        self._notify_state("train_absent_sent")
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
        self._notify_state(f"door_control_{action}_sent")
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
                self._selection_context_key = None
                self.state.selection_valid = False
                self._notify_state("selection_rejected")
                return

            self.state.selection_valid = True
            if self.pending_selection:
                self.selected_doors = self.pending_selection
                self.pending_selection = {}
                self._notify_state("selection_ack")
            else:
                self.state.selection_valid = bool(self.selected_doors) or int(
                    msg.get("selected_count", 0) or 0
                ) > 0
                self._notify_state("selection_ack")
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
            self._notify_state("control_ack")
            return

        if msg_type == "status_ack":
            self.last_status_ack = msg
            self.update_from_status_ack(msg)
            self._notify_state("status_ack")
            print(f"[STATUS_ACK] {msg}")
            return

        if msg_type == "emergency_status":
            self.last_emergency_status = msg
            self.state.emergency = bool(msg.get("active", False))
            if msg.get("status") is not None:
                self.state.platform_status = str(msg["status"])
            self._notify_state("emergency_status")
            print(f"[EMERGENCY_STATUS] {msg}")
            return

        if msg_type == "ack":
            self.last_ack = msg
            self._notify_state("ack")
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
        print(f"selection_context_key={self._selection_context_key}")
        print(f"status_gate_approved={self._status_gate_approved}")
        print(f"last_ack={self.last_ack}")
        print(f"last_selection_ack={self.last_selection_ack}")
        print(f"last_control_ack={self.last_control_ack}")
        print(f"last_status_ack={self.last_status_ack}")
        print(f"last_emergency_status={self.last_emergency_status}")
        print("==============================================\n")
