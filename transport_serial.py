from __future__ import annotations

import json
import threading
import time
from typing import Callable, Optional

import serial

from config import BAUDRATE, IGNORE_SERIAL_PREFIXES, LINE_DELIMITER, SERIAL_PORT, SERIAL_TIMEOUT_SEC


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
    ESP32 없이 중앙제어부 로직만 테스트하기 위한 Mock 클래스.
    최종 프로토콜에 맞춰 ACK / status_report 를 callback 으로 즉시 전달한다.
    """

    def __init__(self, on_message: Optional[Callable[[dict], None]] = None) -> None:
        self.on_message = on_message
        self.connected = False
        self.boot_time = time.monotonic()
        self.last_seq = 0
        self.platform_status = "IDLE"
        self.train_position = "None"
        self.doors_status = {}  # dcu_idx -> dict

    def connect(self) -> None:
        self.connected = True
        print("[MOCK] connected")

    def close(self) -> None:
        self.connected = False
        print("[MOCK] closed")

    def send_json(self, payload: dict) -> None:
        if not self.connected:
            raise RuntimeError("Mock transport is not connected.")

        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        print(f"[MOCK TX] {line}")

        seq = int(payload.get("seq", 0))
        self.last_seq = seq

        doors = payload.get("doors", [])
        if any(d.get("cmd") == "Open" for d in doors):
            self.platform_status = "OPENING"
        elif any(d.get("cmd") == "Close" for d in doors):
            self.platform_status = "CLOSING"
        elif any(d.get("cmd") == "Stop" for d in doors):
            self.platform_status = "IDLE"

        # ACK
        ack = {
            "msg_type": "ack",
            "platform_id": payload.get("platform_id", 1),
            "result": "OK",
            "last_seq": seq,
            "status": self.platform_status,
        }
        if self.on_message:
            self.on_message(ack)

        # 단순 상태 시뮬레이션
        for d in doors:
            dcu_idx = int(d["dcu_idx"])
            cmd = d["cmd"]
            direction = d["dir"]
            dist_step = int(d["dist_step"])

            if cmd == "Open":
                self.doors_status[dcu_idx] = {
                    "dcu_idx": dcu_idx,
                    "state": "Open",
                    "dir": direction,
                    "dist_step": dist_step,
                    "jammed": False,
                    "emergency": False,
                }
                self.platform_status = "OPENED"

            elif cmd == "Close":
                self.doors_status[dcu_idx] = {
                    "dcu_idx": dcu_idx,
                    "state": "Closed",
                    "dir": direction,
                    "dist_step": dist_step,
                    "jammed": False,
                    "emergency": False,
                }
                self.platform_status = "IDLE"

            elif cmd == "Stop":
                prev = self.doors_status.get(dcu_idx)
                self.doors_status[dcu_idx] = {
                    "dcu_idx": dcu_idx,
                    "state": prev["state"] if prev else "Closed",
                    "dir": "None",
                    "dist_step": 0,
                    "jammed": False,
                    "emergency": False,
                }

        status_report = {
            "msg_type": "status_report",
            "platform_id": payload.get("platform_id", 1),
            "status": self.platform_status,
            "last_seq": seq,
            "uptime_ms": int((time.monotonic() - self.boot_time) * 1000),
            "Trainposition": self.train_position,
            "doors_status": [
                self.doors_status[k] for k in sorted(self.doors_status.keys())
            ],
        }
        if self.on_message:
            self.on_message(status_report)
