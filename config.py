from pathlib import Path

# -----------------------------
# Runtime / transport settings
# -----------------------------
USE_MOCK_SERIAL = True      # 테스트할 때
# USE_MOCK_SERIAL = False   # 실제 ESP32 연결할 때

SERIAL_PORT = "COM3"          # Windows 예시. Linux/macOS는 /dev/ttyUSB0 등으로 변경
BAUDRATE = 115200
SERIAL_TIMEOUT_SEC = 0.2
PLATFORM_ID = 1

# -----------------------------
# Data sheet settings
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MOVEMENT_CSV_PATH = DATA_DIR / "Movement_Data.csv"

# 업로드하신 Inputs 시트 기준: 유닛 폭 1.4m, 8분할
UNIT_WIDTH_M = 1.4
UNIT_DIVISIONS = 8
DIST_STEP_MAX = 8
DIST_STEP_WIDTH_M = UNIT_WIDTH_M / UNIT_DIVISIONS  # 0.175m

# 엑셀 Movement_Data 시트의 Open Unit Start/End 값은 사람이 보는 번호(1-based)일 가능성이 큽니다.
# 현재 ESP32 허브 초안은 dcu_idx = 0~80 을 기대하므로 기본값을 True 로 둡니다.
SHEET_UNIT_ID_IS_1_BASED = True
DOOR_ID_MIN = 0
DOOR_ID_MAX = 80

# Stop Error 매칭 허용 오차
STOP_ERROR_MATCH_TOL_M = 1e-6
STOP_ERROR_FALLBACK_MAX_GAP_M = 0.051  # exact 매칭 실패 시 근사 허용

# JSON line protocol
LINE_DELIMITER = "\n"
USE_CRC_PLACEHOLDER = True
CRC_PLACEHOLDER = "TEMP"
