import json
from typing import Optional

import serial


class SerialTransport:
    """
    실제 ESP32 와 유선 시리얼(JSON line protocol)로 통신하는 클래스
    """

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser: Optional[serial.Serial] = None

    def connect(self):
        self.ser = serial.Serial(self.port, baudrate=self.baudrate, timeout=self.timeout)
        print(f"[SERIAL] connected: {self.port} @ {self.baudrate}")

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
        print("[SERIAL] closed")

    def send_json(self, payload: dict):
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("Serial port is not connected.")
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        self.ser.write(line.encode("utf-8"))
        self.ser.flush()
        print(f"[SERIAL SEND] {line.strip()}")

    def read_line(self):
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("Serial port is not connected.")
        line = self.ser.readline().decode("utf-8", errors="ignore").strip()
        if line:
            print(f"[SERIAL RECV] {line}")
        return line


class MockSerialTransport:
    """
    ESP32 없이 중앙제어부 로직만 테스트하기 위한 Mock 클래스
    """

    def __init__(self):
        self.last_payload = None
        self.connected = False

    def connect(self):
        self.connected = True
        print("[MOCK] connected")

    def close(self):
        self.connected = False
        print("[MOCK] closed")

    def send_json(self, payload: dict):
        if not self.connected:
            raise RuntimeError("Mock transport is not connected.")
        self.last_payload = payload
        line = json.dumps(payload, ensure_ascii=False)
        print(f"[MOCK SEND] {line}")

    def read_line(self):
        if not self.connected:
            raise RuntimeError("Mock transport is not connected.")

        if self.last_payload is None:
            return ""

        fake_ack = {
            "platform_id": self.last_payload.get("platform_id", 1),
            "result": "OK",
            "last_seq": self.last_payload.get("seq", 0),
            "status": "OPENING"
        }
        line = json.dumps(fake_ack, ensure_ascii=False)
        print(f"[MOCK RECV] {line}")
        self.last_payload = None
        return line