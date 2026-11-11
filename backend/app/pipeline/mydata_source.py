"""마이데이터 원천 로더

실제 마이데이터 연동 시 이 모듈의 `load_user_data`만 표준 API 호출로 교체하면
분류 이후 파이프라인은 그대로 재사용된다. (1차는 규격 기반 테스트 데이터 JSON 사용)
"""
import json
from pathlib import Path
from typing import Dict

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
MYDATA_DIR = DATA_DIR / "mydata"

_FILES = [
    "bank_accounts", "bank_transactions", "bank_loans", "capital_loans", "card_approvals",
    "card_bills", "card_loans", "efin_accounts", "insurance_list", "invest_accounts",
    "irp_accounts", "telecom_contracts",
]


def user_dir(user_id: int) -> Path:
    return MYDATA_DIR / f"user_{user_id:03d}"


def load_user_data(path: Path) -> Dict[str, dict]:
    """user_XXX 디렉터리의 마이데이터 응답 JSON들을 {파일명: payload}로 읽는다.

    규격 외 내부 필드(`_category`, `_is_fixed` 등 정답 힌트)는 분류에 사용하지 않는다.
    (평가 스크립트만 별도로 읽는다.)
    """
    data: Dict[str, dict] = {}
    for name in _FILES:
        f = path / f"{name}.json"
        if f.exists():
            with open(f, encoding="utf-8") as fp:
                data[name] = json.load(fp)
        else:
            data[name] = {}
    return data
