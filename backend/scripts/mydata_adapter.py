"""마이데이터 원천 JSON → AFPA 내부 DB 모델 변환 어댑터

data/mydata/user_XXX/*.json (마이데이터 표준 API 응답 형식)을 읽어
기존 DB 모델(User/FinancialProfile/Goal/Transaction)로 변환한다.

실전 마이데이터 연동 시 이 어댑터의 "파일 읽기" 부분만 실제 API 호출로
교체하면 나머지 파이프라인은 그대로 재사용된다.

변환 규칙:
    은행 수신잔액(입출금)+전금 잔액       → FinancialProfile.deposit  (예금)
    은행 정기예금+적금                    → deposit/savings 분리
    금투 평가금액                         → FinancialProfile.investment
    IRP 평가금액                          → FinancialProfile.other_assets
    은행대출+카드대출(리볼빙/단기)+할부금융 → FinancialProfile.total_debt
    카드 승인내역                         → Transaction (변동지출, 가맹점→카테고리)
    보험 납입/통신 결제/주거·공과금 이체    → Transaction (고정지출)
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MYDATA_DIR = DATA_DIR / "mydata"

# 가맹점명 → 소비 카테고리 매핑 (승인내역의 _category 힌트가 없을 때 폴백)
MERCHANT_CATEGORY_KEYWORDS = {
    "식비": ["김밥", "맘스터치", "배달", "GS25", "이마트", "맥도날드"],
    "쇼핑": ["쿠팡", "무신사", "올리브영", "네이버쇼핑", "다이소"],
    "교통": ["카카오T", "코레일", "교통공사", "주유소", "칼텍스"],
    "문화/여가": ["CGV", "교보문고", "인터파크", "볼링"],
    "카페/간식": ["스타벅스", "메가커피", "투썸", "배스킨"],
    "의료/건강": ["약국", "외과", "GNC", "병원", "의원"],
    "구독서비스": ["넷플릭스", "유튜브", "멜론", "쿠팡와우"],
}


def _load(user_dir: Path, name: str) -> dict:
    path = user_dir / name
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _parse_dtime(s: str) -> datetime:
    return datetime.strptime(s, "%Y%m%d%H%M%S")


def _categorize(merchant_name: Optional[str]) -> str:
    if not merchant_name:
        return "기타"
    for category, keywords in MERCHANT_CATEGORY_KEYWORDS.items():
        if any(kw in merchant_name for kw in keywords):
            return category
    return "기타"


# ---------------------------------------------------------------------------
# 사용자별 변환
# ---------------------------------------------------------------------------
def convert_user(user_dir: Path) -> dict:
    """user_XXX 디렉터리 → {user, profile, goals, transactions} 딕셔너리"""
    meta = _load(user_dir, "_user.json")
    user_id = meta["user_id"]

    # ---------- 자산 집계 ----------
    bank = _load(user_dir, "bank_accounts.json")
    checking = deposit = savings = 0.0
    for detail in bank.get("detail_list", []):
        acc_type = next(
            (a["account_type"] for a in bank.get("account_list", [])
             if a["account_num"] == detail["account_num"]), "")
        bal = detail.get("balance_amt", 0) or 0
        if acc_type == "1001":
            checking += bal
        elif acc_type == "1002":
            deposit += bal
        elif acc_type == "1003":
            savings += bal

    efin = _load(user_dir, "efin_accounts.json")
    efin_balance = sum(b.get("balance_amt", 0) or 0 for b in efin.get("balance_list", []))

    invest = _load(user_dir, "invest_accounts.json")
    investment = 0.0
    for b in invest.get("basic_list", []):
        investment += b.get("withholdings_amt", 0) or 0
    for pr in invest.get("product_list", []):
        investment += pr.get("eval_amt", 0) or 0

    irp = _load(user_dir, "irp_accounts.json")
    irp_amt = sum(d.get("eval_amt", 0) or 0 for d in irp.get("detail_list", []))

    # ---------- 부채 집계 ----------
    bank_loans = _load(user_dir, "bank_loans.json")
    debt = sum(d.get("balance_amt", 0) or 0 for d in bank_loans.get("detail_list", []))

    card_loans = _load(user_dir, "card_loans.json")
    debt += sum(r.get("remain_amt", 0) or 0 for r in card_loans.get("revolving_list", []))
    debt += sum(s.get("remain_amt", 0) or 0 for s in card_loans.get("short_term_list", []))
    debt += sum(l.get("remain_amt", 0) or 0 for l in card_loans.get("long_term_list", []))

    capital = _load(user_dir, "capital_loans.json")
    debt += sum(d.get("balance_amt", 0) or 0 for d in capital.get("detail_list", []))

    profile = {
        "monthly_income": meta["monthly_income"],
        "monthly_fixed_expense": meta["monthly_fixed_expense"],
        "monthly_variable_expense": meta["monthly_variable_expense"],
        "deposit": checking + deposit + efin_balance,
        "savings": savings,
        "investment": investment,
        "other_assets": irp_amt,
        "total_debt": debt,
    }

    # ---------- 거래내역 변환 ----------
    transactions = []

    # 1) 카드 승인내역 → 변동지출 (+구독 고정지출)
    approvals = _load(user_dir, "card_approvals.json")
    for ap in approvals.get("approved_list", []):
        if ap.get("status") != "01":  # 승인 취소 제외
            continue
        category = ap.get("_category") or _categorize(ap.get("merchant_name"))
        transactions.append({
            "user_id": user_id,
            "amount": ap["approved_amt"],
            "category": category,
            "is_fixed": bool(ap.get("_is_fixed", False)),
            "description": ap.get("merchant_name"),
            "transacted_at": _parse_dtime(ap["approved_dtime"]),
        })

    # 2) 은행 거래내역 중 고정지출(주거/공과금) → 고정지출
    bank_trans = _load(user_dir, "bank_transactions.json")
    for tr in bank_trans.get("trans_list", []):
        memo = tr.get("trans_memo", "") or ""
        if "월세" in memo or "관리비" in memo:
            cat = "주거"
        elif "전기" in memo or "가스" in memo or "수도" in memo:
            cat = "공과금"
        else:
            continue  # 급여/카드대금/적금이체는 소비 아님
        transactions.append({
            "user_id": user_id,
            "amount": tr["trans_amt"],
            "category": cat,
            "is_fixed": True,
            "description": memo,
            "transacted_at": _parse_dtime(tr["trans_dtime"]),
        })

    # 3) 보험 납입 → 고정지출 (매월 납입액을 각 월에 기록)
    insu = _load(user_dir, "insurance_list.json")
    monthly_prem = sum(
        p.get("pay_amt", 0) or 0
        for p in insu.get("payment_list", [])
        if p.get("pay_due") == "01"  # 매월 납입만
    )
    # 4) 통신 결제 → 고정지출
    telecom = _load(user_dir, "telecom_contracts.json")

    # 보험/통신은 은행 거래내역과 같은 월 주기 — 통신 paid_list 기준 월 목록 사용
    for paid in telecom.get("paid_list", []):
        ts = _parse_dtime(paid["paid_dtime"])
        transactions.append({
            "user_id": user_id, "amount": paid["paid_amt"], "category": "통신",
            "is_fixed": True, "description": "통신요금", "transacted_at": ts,
        })
        if monthly_prem > 0:
            transactions.append({
                "user_id": user_id, "amount": monthly_prem, "category": "보험",
                "is_fixed": True, "description": "보험료 납입", "transacted_at": ts,
            })

    return {
        "user": {
            "id": user_id, "name": meta["name"], "job": meta.get("job"),
            "persona_type": meta.get("persona_type"), "description": meta.get("description"),
        },
        "profile": profile,
        "goals": meta.get("goals", []),
        "transactions": transactions,
    }


def convert_all() -> list:
    """모든 user_XXX 디렉터리 변환"""
    if not MYDATA_DIR.exists():
        raise FileNotFoundError(
            f"{MYDATA_DIR} 가 없습니다. 먼저 `python -m scripts.generate_mydata` 를 실행하세요."
        )
    results = []
    for user_dir in sorted(MYDATA_DIR.glob("user_*")):
        results.append(convert_user(user_dir))
    return results
