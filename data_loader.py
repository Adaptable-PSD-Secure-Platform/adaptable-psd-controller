from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from config import CSV_ENCODINGS, MOVEMENT_CSV_PATH


@dataclass(frozen=True)
class MovementRow:
    train_type: str
    door_no: int
    case: int
    stop_error_m: float
    open_unit_start: int
    open_unit_end: int
    direction: str
    move_distance_m: float
    valid: str


class MovementDataRepository:
    """
    Movement_Data.csv 로부터 lookup 용 데이터를 읽는 저장소.
    런타임에는 이 CSV 하나만 사용하고, Inputs / Train_Door_DB 는 참조용으로 분리 보관합니다.
    """

    def __init__(self, csv_path: Path = MOVEMENT_CSV_PATH) -> None:
        self.csv_path = Path(csv_path)
        self.rows: List[MovementRow] = []
        self.index: Dict[str, List[MovementRow]] = {}
        self.load()

    @staticmethod
    def _clean_key(key: str) -> str:
        return key.strip().replace("\ufeff", "")

    def _open_with_fallback(self):
        last_error = None
        for enc in CSV_ENCODINGS:
            try:
                f = self.csv_path.open("r", encoding=enc, newline="")
                # 실제 디코딩 테스트
                f.read(1024)
                f.seek(0)
                print(f"[DATA] CSV encoding detected: {enc}")
                return f
            except UnicodeDecodeError as exc:
                last_error = exc
                try:
                    f.close()
                except Exception:
                    pass
        if last_error:
            raise last_error
        raise RuntimeError("CSV 파일을 열 수 없습니다.")

    def load(self) -> None:
        if not self.csv_path.exists():
            raise FileNotFoundError(
                f"Movement_Data.csv 파일을 찾을 수 없습니다: {self.csv_path}\n"
                f"엑셀의 Movement_Data 시트를 UTF-8 CSV 로 export 해서 data 폴더에 넣어주세요."
            )

        self.rows.clear()
        self.index.clear()

        with self._open_with_fallback() as f:
            reader = csv.DictReader(f)
            fieldnames = [self._clean_key(name) for name in (reader.fieldnames or [])]
            normalized_rows = []
            for raw in reader:
                row = {
                    self._clean_key(k): (v.strip() if isinstance(v, str) else v)
                    for k, v in raw.items()
                }
                normalized_rows.append(row)

        required_cols = {
            "Train Type",
            "Door No.",
            "Case",
            "Stop Error (m)",
            "Open Unit Start",
            "Open Unit End",
            "Direction",
            "Move Distance (m)",
            "Valid?",
        }
        missing = required_cols - set(fieldnames)
        if missing:
            raise ValueError(
                "Movement_Data.csv 필수 컬럼이 부족합니다.\n"
                f"missing={sorted(missing)}\n"
                f"found={fieldnames}"
            )

        for row in normalized_rows:
            item = MovementRow(
                train_type=row["Train Type"],
                door_no=int(float(row["Door No."])),
                case=int(float(row["Case"])),
                stop_error_m=float(row["Stop Error (m)"]),
                open_unit_start=int(float(row["Open Unit Start"])),
                open_unit_end=int(float(row["Open Unit End"])),
                direction=row["Direction"],
                move_distance_m=float(row["Move Distance (m)"]),
                valid=row["Valid?"],
            )
            self.rows.append(item)
            self.index.setdefault(item.train_type, []).append(item)

    def get_rows_for_train(self, train_type: str) -> List[MovementRow]:
        return self.index.get(train_type, [])
