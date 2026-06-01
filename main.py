from __future__ import annotations

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
reset                      -> operator/controller 상태 초기화
reload                     -> Movement_Data.csv 다시 읽기
seq-reset                  -> 다음 명령을 seq=0 으로 전송

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

quit
""".strip()
    )


def main() -> None:
    repo = MovementDataRepository()
    controller: CentralController

    def on_serial_message(msg: dict) -> None:
        controller.handle_feedback(msg)

    if USE_MOCK_SERIAL:
        transport = MockSerialTransport(on_message=on_serial_message)
    else:
        transport = SerialTransport(
            port=SERIAL_PORT,
            baudrate=BAUDRATE,
            on_message=on_serial_message,
        )

    controller = CentralController(
        platform_id=PLATFORM_ID,
        repo=repo,
        transport=transport,
    )

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

                elif cmd == "seq-reset":
                    controller.reset_seq()

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

                elif cmd == "reset":
                    controller.reset_state()

                elif cmd == "open":
                    controller.send_open()

                elif cmd == "close":
                    controller.send_close()

                elif cmd == "stop":
                    controller.send_stop(all_doors=False)

                elif cmd == "stop-all":
                    controller.send_stop(all_doors=True)

                elif cmd == "emergency" and len(parts) == 2:
                    controller.set_emergency(parts[1].lower() == "on")

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
