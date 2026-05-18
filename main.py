from __future__ import annotations

import json

from central_controller import CentralController
from config import PLATFORM_ID, USE_MOCK_SERIAL, SERIAL_PORT, BAUDRATE
from data_loader import MovementDataRepository
from transport_serial import SerialTransport, MockSerialTransport


def print_help() -> None:
    print(
        """
사용 가능한 명령
-----------------
help
state
reload                     -> Movement_Data.csv 다시 읽기

train GTX-A                -> AI 결과 대입
case 3                     -> 정차 case 대입
error 0.05                 -> stop_error_m 대입
stopped on|off             -> 정차 완료 입력
open-ok on|off             -> 개방 승인
close-ok on|off            -> 닫힘 승인

open                       -> OPEN JSON 전송
close                      -> CLOSE JSON 전송
stop                       -> active doors STOP
stop-all                   -> 전체 STOP
emergency on|off           -> 비상 상태 전환

poll                       -> 시리얼/Mock 응답 1회 읽기
quit
""".strip()
    )


def main() -> None:
    repo = MovementDataRepository()

    if USE_MOCK_SERIAL:
        transport = MockSerialTransport()
    else:
        transport = SerialTransport(SERIAL_PORT, BAUDRATE)

    controller = CentralController(
        platform_id=PLATFORM_ID,
        repo=repo,
        transport=transport,
    )

    def poll_transport_once() -> None:
        try:
            line = transport.read_line()
            if not line:
                return
            msg = json.loads(line)
            controller.handle_feedback(msg)
        except json.JSONDecodeError:
            print("[WARN] 수신 데이터가 JSON 형식이 아닙니다.")
        except Exception as exc:
            print(f"[WARN] 수신 처리 중 오류: {exc}")

    transport.connect()
    print_help()

    try:
        while True:
            raw = input("ccu> ").strip()
            if not raw:
                continue

            parts = raw.split()
            cmd = parts[0].lower()

            try:
                if cmd == "help":
                    print_help()

                elif cmd == "state":
                    controller.print_state()

                elif cmd == "reload":
                    repo.load()
                    print("[INFO] Movement_Data.csv reloaded")

                elif cmd == "train" and len(parts) >= 2:
                    controller.update_train_type(" ".join(parts[1:]))

                elif cmd == "case" and len(parts) == 2:
                    current_error = controller.state.stop_error_m or 0.0
                    controller.update_stop_context(int(parts[1]), current_error)

                elif cmd == "error" and len(parts) == 2:
                    current_case = controller.state.case or 1
                    controller.update_stop_context(current_case, float(parts[1]))

                elif cmd == "stopped" and len(parts) == 2:
                    controller.set_stopped(parts[1].lower() == "on")

                elif cmd == "open-ok" and len(parts) == 2:
                    controller.set_open_approved(parts[1].lower() == "on")

                elif cmd == "close-ok" and len(parts) == 2:
                    controller.set_close_approved(parts[1].lower() == "on")

                elif cmd == "open":
                    controller.send_open()
                    poll_transport_once()

                elif cmd == "close":
                    controller.send_close()
                    poll_transport_once()

                elif cmd == "stop":
                    controller.send_stop(all_doors=False)
                    poll_transport_once()

                elif cmd == "stop-all":
                    controller.send_stop(all_doors=True)
                    poll_transport_once()

                elif cmd == "emergency" and len(parts) == 2:
                    controller.set_emergency(parts[1].lower() == "on")

                elif cmd == "poll":
                    poll_transport_once()

                elif cmd == "quit":
                    break

                else:
                    print("[ERROR] 알 수 없는 명령입니다. help 를 입력하세요.")

            except Exception as exc:
                print(f"[ERROR] {exc}")

    finally:
        transport.close()


if __name__ == "__main__":
    main()