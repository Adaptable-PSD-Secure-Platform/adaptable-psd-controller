from ultralytics import YOLO
from collections import Counter
from pathlib import Path
import cv2
import time
import json

model = YOLO("best.pt")

# ── 판단 설정값 ──
WINDOW_SIZE = 15
CONFIDENCE_THRESHOLD = 0.75
DECISION_THRESHOLD = 0.60

# ── 클래스 이름 변환 테이블 ──
# 현재 AUSD 룩업 테이블의 열차명에 맞춥니다.
CLASS_MAP = {
    "ktx1": "KTX-1",
    "ktx2": "KTX-산천",
    "cube": "지하철 대형통근형",
    "nuri": "누리로",
    "itx": "다른 열차",
    "mugungwha": "다른 열차",
    "srt": "KTX-산천",
}

# ── 제어 대상 열차 ──
CONTROLLABLE = [
    "GTX-A",
    "KTX-1",
    "KTX-산천",
    "KTX-청룡",
    "KTX-이음",
    "누리로",
    "지하철 대형통근형",
]

# ── AI 결과 저장 파일 ──
AI_RESULT_PATH = Path("ai_result.json")
print(f"[AI] save path = {AI_RESULT_PATH.resolve()}")

# ── 판단 변수 초기화 ──
vote_window = []
final_decision = None
decision_locked = False
decision_frame = 0
frame_count = 0
start_time = time.time()

# ── 웹캠 열기 ──
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

if not cap.isOpened():
    print("[ERROR] 웹캠을 열 수 없습니다. camera index를 확인하세요.")
    raise SystemExit(1)

print("웹캠 시작 - q: 종료 | r: 판단 초기화\n")


def save_ai_result(train_type: str, frame_no: int, elapsed_sec: float) -> None:
    payload = {
        "train_type": train_type,
        "frame": frame_no,
        "elapsed_sec": round(elapsed_sec, 2),
        "locked": True,
    }
    AI_RESULT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[AI] 결과 저장 완료: {AI_RESULT_PATH.resolve()}")
    print(f"[AI] saved train_type = {train_type}")


def clear_ai_result() -> None:
    if AI_RESULT_PATH.exists():
        AI_RESULT_PATH.unlink()
        print(f"[AI] 결과 파일 삭제: {AI_RESULT_PATH.resolve()}")


while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        print("[ERROR] 프레임을 읽지 못했습니다.")
        break

    frame_count += 1

    # ── YOLO 추론 ──
    results = model(frame, conf=0.5, verbose=False)

    if not decision_locked:
        for box in results[0].boxes:
            conf = float(box.conf[0])
            raw_cls = results[0].names[int(box.cls[0])]

            if conf >= CONFIDENCE_THRESHOLD:
                vote_window.append(raw_cls)

        # 슬라이딩 윈도우
        if len(vote_window) > WINDOW_SIZE:
            vote_window = vote_window[-WINDOW_SIZE:]

        # 판단 조건 체크
        if len(vote_window) == WINDOW_SIZE:
            counter = Counter(vote_window)
            top_cls, top_count = counter.most_common(1)[0]

            if top_count >= WINDOW_SIZE * DECISION_THRESHOLD:
                # ── 클래스 이름 변환 ──
                final_decision = CLASS_MAP.get(top_cls, top_cls)
                decision_locked = True
                decision_frame = frame_count
                elapsed = time.time() - start_time

                print(f"[{frame_count}프레임 | {elapsed:.1f}초] 최종 판단 확정: {final_decision}")
                print(f"   투표 현황: {dict(counter)}")

                save_ai_result(final_decision, decision_frame, elapsed)

    # ── 화면 표시 ──
    annotated = results[0].plot()

    if final_decision:
        color = (0, 255, 0) if final_decision in CONTROLLABLE else (0, 165, 255)
        cv2.putText(
            annotated,
            f"DECISION: {final_decision}",
            (10, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.3,
            color,
            4,
        )
    else:
        cv2.putText(
            annotated,
            f"Voting: {len(vote_window)}/{WINDOW_SIZE}",
            (10, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 165, 255),
            2,
        )

    cv2.imshow("FUSD - 열차 인식 시스템", annotated)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    elif key == ord("r"):
        vote_window = []
        final_decision = None
        decision_locked = False
        decision_frame = 0
        clear_ai_result()
        print("판단 초기화됨\n")

cap.release()
cv2.destroyAllWindows()

elapsed_total = time.time() - start_time

print("=" * 55)
print("분석 결과 요약")
print("=" * 55)

if final_decision:
    print(f"  열차 종류    : {final_decision}")
    print(f"  확정 프레임  : {decision_frame}번째")
    print(f"  전체 프레임  : {frame_count}개")
    print(f"  총 경과 시간 : {elapsed_total:.1f}초")
else:
    print("  판단 실패")
    print(f"  현재 투표    : {len(vote_window)}/{WINDOW_SIZE}")
    print("  → 더 오래 보여주거나 CONFIDENCE_THRESHOLD를 낮춰보세요")

print("=" * 55)
