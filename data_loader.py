from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from config import AUSD_LOOKUP_CSV_PATH, CSV_ENCODINGS


REQUIRED_COLUMNS = {
    "Train Type",
    "Door No.",
    "Case",
    "Stop Error (mm)",
    "Unit ID",
    "Direction",
    "Move Distance (mm)",
    "Valid?",
}


@dataclass(frozen=True)
class AUSDLookupRow:
    train_type: str
    door_no: int
    case: int
    stop_error_m: float
    unit_id: int
    direction: str
    move_distance_m: float
    valid: str


class AUSDLookupRepository:
    """
    AUSD_Lookup_135_final.csv를 읽는 저장소.
    AUSD 원본의 mm 단위와 1-based Unit ID를 런타임 형식으로 변환합니다.
    """

    def __init__(self, csv_path: Path = AUSD_LOOKUP_CSV_PATH) -> None:
        self.csv_path = Path(csv_path)
        self.rows: List[AUSDLookupRow] = []
        self.index: Dict[str, List[AUSDLookupRow]] = {}
        self.load()

    @staticmethod
    def _clean_key(key: object) -> str:
        return str(key or "").strip().replace("\ufeff", "")

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
                f"AUSD 룩업 CSV 파일을 찾을 수 없습니다: {self.csv_path}\n"
                f"data 폴더에 AUSD_Lookup_135_final.csv 파일을 넣어주세요."
            )

        self.rows.clear()
        self.index.clear()

        with self._open_with_fallback() as f:
            reader = csv.DictReader(f)
            fieldnames = [self._clean_key(name) for name in (reader.fieldnames or [])]
            missing = REQUIRED_COLUMNS - set(fieldnames)
            if missing:
                raise ValueError(
                    "AUSD_Lookup_135_final.csv 필수 컬럼이 부족합니다.\n"
                    f"missing={sorted(missing)}\n"
                    f"found={fieldnames}"
                )

            for raw in reader:
                if not any(value not in (None, "") for value in raw.values()):
                    continue
                row = {
                    self._clean_key(k): (v.strip() if isinstance(v, str) else v)
                    for k, v in raw.items()
                }

                item = AUSDLookupRow(
                    train_type=row["Train Type"],
                    door_no=int(float(row["Door No."])),
                    case=int(float(row["Case"])),
                    stop_error_m=float(row["Stop Error (mm)"]) / 1000.0,
                    unit_id=int(float(row["Unit ID"])),
                    direction=row["Direction"],
                    move_distance_m=float(row["Move Distance (mm)"]) / 1000.0,
                    valid=row["Valid?"],
                )
                self.rows.append(item)
                self.index.setdefault(item.train_type, []).append(item)

        if not self.rows:
            raise ValueError(
                "AUSD_Lookup_135_final.csv에 읽을 수 있는 데이터 행이 없습니다."
            )

        print(f"[DATA] AUSD lookup loaded: rows={len(self.rows)}")

    def get_rows_for_train(self, train_type: str) -> List[AUSDLookupRow]:
        return self.index.get(self._clean_key(train_type), [])
