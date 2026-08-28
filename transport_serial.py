from __future__ import annotations

import json
import threading
import time
from typing import Callable, Optional

import serial

from config import (
    BAUDRATE,
    DOOR_ID_MAX,
    DOOR_ID_MIN,
    IGNORE_SERIAL_PREFIXES,
    LINE_DELIMITER,
    SERIAL_PORT,
    SERIAL_TIMEOUT_SEC,
)


class SerialTransport:
    """
    실제 ESP32 와 유선 시리얼(JSON line protocol)로 통신하는 클래스.
    - 송신: JSON 1줄 + '\n'
    - 수신: readline() 백그라운드 스레드
    - [DEBUG] 로 시작하는 디버그 문자열은 무시
    """

    def __init__(
        self,
        port: str = SERIAL_PORT,
        baudrate: int = BAUDRATE,
        timeout: float = SERIAL_TIMEOUT_SEC,
        on_message: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.on_message = on_message
        self.ser: Optional[serial.Serial] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def connect(self) -> None:
        self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        self._running = True
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()
        print(f"[SERIAL] connected: {self.port} @ {self.baudrate}")

    def close(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self.ser and self.ser.is_open:
            self.ser.close()
        print("[SERIAL] closed")

    def send_json(self, payload: dict) -> None:
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("Serial port is not connected.")
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + LINE_DELIMITER
        self.ser.write(line.encode("utf-8"))
        self.ser.flush()
        print(f"[SERIAL TX] {line.strip()}")

    def _reader_loop(self) -> None:
        assert self.ser is not None
        while self._running:
            try:
                raw = self.ser.readline()
                if not raw:
                    continue

                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                if any(line.startswith(prefix) for prefix in IGNORE_SERIAL_PREFIXES):
                    print(f"[SERIAL DEBUG IGNORED] {line}")
                    continue

                if not line.startswith("{"):
                    print(f"[SERIAL NON-JSON IGNORED] {line}")
                    continue

                print(f"[SERIAL RX] {line}")

                if self.on_message is None:
                    continue

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    print(f"[SERIAL JSON ERROR] {line}")
                    continue

                self.on_message(msg)

            except Exception as exc:
                print(f"[SERIAL] reader error: {exc}")
                time.sleep(0.05)


class MockSerialTransport:
    """
    ESP32 없이 New JSON 중앙제어부 로직을 테스트하기 위한 Mock 클래스.
    train_context 승인, 제어 ACK, status_ack, emergency_status를 시뮬레이션합니다.
    """

    def __init__(
        self,
        platform_id: int = 1,
        on_message: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.platform_id = platform_id
        self.on_message = on_message
        self.connected = False
        self.boot_time = time.monotonic()
        self.last_seq = 0
        self.platform_status = "IDLE"
        self.initialized = True
        self.train_state = "STOPPED"
        self.case = 1
        self.position_valid = True
        self.selection_valid = False
        self.emergency = False
        self.selected_doors = {}  # dcu_idx -> {dir, open_dist_step}
        self.doors_status = {}  # dcu_idx -> dict

    def connect(self) -> None:
        self.connected = True
        print("[MOCK] connected")

    def close(self) -> None:
        self.connected = False
        print("[MOCK] closed")

    def _emit(self, message: dict) -> None:
        if self.on_message:
            self.on_message(message)

    @staticmethod
    def _door_status(
        dcu_idx: int,
        state: str = "Closed",
        direction: str = "None",
        dist_step: int = 0,
        emergency: bool = False,
    ) -> dict:
        return {
            "dcu_idx": dcu_idx,
            "dcu_id": dcu_idx // 4,
            "channel": dcu_idx % 4,
            "state": state,
            "dir": direction,
            "dist_step": dist_step,
            "jammed": False,
            "emergency": emergency,
        }

    def _status_doors(self, scope: str) -> list:
        if scope == "active":
            door_ids = sorted(self.selected_doors.keys())
        else:
            door_ids = range(DOOR_ID_MIN, DOOR_ID_MAX + 1)

        result = []
        for dcu_idx in door_ids:
            result.append(
                self.doors_status.get(
                    dcu_idx,
                    self._door_status(dcu_idx),
                )
            )
        return result

    def _emit_status_ack(self, request_seq: int, scope: str) -> None:
        doors_status = self._status_doors(scope)
        self._emit(
            {
                "msg_type": "status_ack",
                "platform_id": self.platform_id,
                "result": "OK",
                "request_seq": request_seq,
                "status": self.platform_status,
                "initialized": self.initialized,
                "train_state": self.train_state,
                "case": self.case,
                "position_valid": self.position_valid,
                "selection_valid": self.selection_valid,
                "doors_status": doors_status,
                "reported_door_count": len(doors_status),
            }
        )

    def _emit_control_ack(self, seq: int, command: str, result: str = "OK", result_code: int = 0) -> None:
        message = {
            "msg_type": "control_ack",
            "platform_id": self.platform_id,
            "command": command,
            "result": result,
            "result_code": result_code,
            "last_seq": seq,
            "status": self.platform_status,
        }
        if result == "OK":
            message["reason"] = "Command accepted"
        self._emit(message)

    def send_json(self, payload: dict) -> None:
        if not self.connected:
            raise RuntimeError("Mock transport is not connected.")

        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        print(f"[MOCK TX] {line}")

        seq = int(payload.get("seq", 0))
        self.last_seq = seq
        msg_type = payload.get("msg_type")

        if msg_type == "status_request":
            scope = str(payload.get("scope", "")).lower()
            if scope not in {"active", "all"}:
                self._emit(
                    {
                        "msg_type": "ack",
                        "platform_id": self.platform_id,
                        "result": "ERROR",
                        "last_seq": seq,
                        "status": self.platform_status,
                        "reason": "Invalid status_request scope",
                    }
                )
                return
            self._emit_status_ack(seq, scope)
            return

        if msg_type == "train_context":
            if payload.get("train_present") is False:
                self.selected_doors.clear()
                self.doors_status.clear()
                self.selection_valid = False
                self.train_state = "EMPTY"
                self.case = None
                selected_count = 0
            else:
                self.selected_doors = {
                    int(door["dcu_idx"]): {
                        "dir": door["dir"],
                        "open_dist_step": int(door["open_dist_step"]),
                    }
                    for door in payload.get("doors", [])
                }
                self.case = int(payload["case"])
                self.selection_valid = True
                selected_count = len(self.selected_doors)
                for dcu_idx, selection in self.selected_doors.items():
                    self.doors_status[dcu_idx] = self._door_status(
                        dcu_idx,
                        direction=selection["dir"],
                        dist_step=selection["open_dist_step"],
                    )

            self._emit(
                {
                    "msg_type": "selection_ack",
                    "platform_id": self.platform_id,
                    "result": "OK",
                    "result_code": 0,
                    "last_seq": seq,
                    "case": self.case,
                    "selected_count": selected_count,
                }
            )
            return

        if msg_type == "door_control":
            action = str(payload.get("action", "")).lower()
            command = action.upper()
            if action not in {"open", "close", "stop"}:
                self._emit_control_ack(seq, command, "ERROR", 4)
                return
            if self.emergency:
                self._emit_control_ack(seq, command, "ERROR", 2)
                return
            if not self.selection_valid or not self.selected_doors:
                self._emit_control_ack(seq, command, "ERROR", 4)
                return

            if action == "open":
                self.platform_status = "OPENING"
                for dcu_idx, selection in self.selected_doors.items():
                    self.doors_status[dcu_idx] = self._door_status(
                        dcu_idx,
                        state="Opening",
                        direction=selection["dir"],
                        dist_step=selection["open_dist_step"],
                    )
            elif action == "close":
                self.platform_status = "CLOSING"
                for dcu_idx, selection in self.selected_doors.items():
                    self.doors_status[dcu_idx] = self._door_status(
                        dcu_idx,
                        state="Closing",
                        direction=selection["dir"],
                        dist_step=selection["open_dist_step"],
                    )
            else:
                self.platform_status = "IDLE"
                for dcu_idx, previous in self.doors_status.items():
                    if dcu_idx in self.selected_doors:
                        self.doors_status[dcu_idx] = self._door_status(
                            dcu_idx,
                            state="Stopped",
                            direction=previous["dir"],
                            dist_step=previous["dist_step"],
                        )

            self._emit_control_ack(seq, command)
            return

        if msg_type == "emergency_control":
            action = str(payload.get("action", "")).lower()
            if action == "enter":
                self.emergency = True
                self.platform_status = "EMERGENCY"
                for dcu_idx in self.doors_status:
                    self.doors_status[dcu_idx]["emergency"] = True
                self._emit_control_ack(seq, "EMERGENCY")
                self._emit(
                    {
                        "msg_type": "emergency_status",
                        "platform_id": self.platform_id,
                        "active": True,
                        "source": "PC",
                        "reason_code": 2,
                        "status": "EMERGENCY",
                        "cause": "PC emergency_control enter",
                    }
                )
                return
            if action == "release":
                self.emergency = False
                self.platform_status = "IDLE"
                for dcu_idx in self.doors_status:
                    self.doors_status[dcu_idx]["emergency"] = False
                self._emit_control_ack(seq, "RECOVERY")
                self._emit(
                    {
                        "msg_type": "emergency_status",
                        "platform_id": self.platform_id,
                        "active": False,
                        "source": "NONE",
                        "reason_code": 0,
                        "status": "IDLE",
                        "cause": "Recovery command delivered to all DCUs",
                    }
                )
                return

            self._emit_control_ack(seq, "EMERGENCY", "ERROR", 4)
            return

        self._emit(
            {
                "msg_type": "ack",
                "platform_id": self.platform_id,
                "result": "ERROR",
                "last_seq": seq,
                "status": self.platform_status,
                "reason": f"Unsupported msg_type: {msg_type}",
            }
        )
