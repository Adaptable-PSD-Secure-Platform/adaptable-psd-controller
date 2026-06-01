from pathlib import Path

# -----------------------------
# Runtime / transport settings
# -----------------------------
USE_MOCK_SERIAL = False       # True: ESP32 없이 Mock 테스트, False: 실제 ESP32 시리얼 연결
SERIAL_PORT = "COM4"         # Windows 예시. Linux/macOS는 /dev/ttyUSB0 등으로 변경
BAUDRATE = 115200            # PDF 규격: PC ↔ Hub USB Serial 115200 bps
SERIAL_TIMEOUT_SEC = 0.2
PLATFORM_ID = 1
LINE_DELIMITER = "\n"

# DEBUG_MODE=true 인 ESP32가 [DEBUG] 문자열을 Serial로 섞어 보낼 수 있으므로 무시할 prefix
IGNORE_SERIAL_PREFIXES = ("[DEBUG]",)

# -----------------------------
# Data sheet settings
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MOVEMENT_CSV_PATH = DATA_DIR / "Movement_Data.csv"

# Inputs 시트 기준
UNIT_WIDTH_M = 1.4
UNIT_DIVISIONS = 8
DIST_STEP_MAX = 8
DIST_STEP_WIDTH_M = UNIT_WIDTH_M / UNIT_DIVISIONS  # 0.175m
SHEET_UNIT_ID_IS_1_BASED = True

# Hub 규격 (PDF 4.1): dcu_idx 0~159
DOOR_ID_MIN = 0
DOOR_ID_MAX = 159

# Stop Error 매칭 허용 오차
STOP_ERROR_MATCH_TOL_M = 1e-6
STOP_ERROR_FALLBACK_MAX_GAP_M = 0.051

# CSV 인코딩 fallback
CSV_ENCODINGS = ("utf-8-sig", "cp949", "euc-kr", "utf-8")
