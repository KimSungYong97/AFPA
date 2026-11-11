"""마이데이터 → 5대분류 자동 분류 (자산 / 부채 / 수입 / 고정지출 / 변동지출)

기준: 1차 = 구조화 필드(계좌유형·상환방식 코드, 주기성), 보조 = 텍스트(가맹점명·적요).
가맹점 분류는 MerchantClassifier의 4단계 폴백을 따른다.
"""
import calendar
from collections import Counter
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple

from app.pipeline import params
from app.pipeline.dictionary import (
    BANK_ACCOUNT_TYPE, BANK_NAME_FALLBACK, CARD_BILL_KEYWORDS, DEDICATED_SOURCE_KEYWORDS,
    FIXED_CATEGORIES, INCOME_KEYWORDS, INVEST_PROD_TYPE, LOAN_NAME_FALLBACK, LOAN_TYPE_PREFIX,
    SAVING_TRANSFER_KEYWORDS, UNCLASSIFIED, UTILITY_LIKE_CATEGORIES, major_for_category,
)
from app.pipeline.merchant import MerchantClassifier
from app.pipeline.recurrence import Occurrence, detect_recurring
from app.pipeline.text import normalize_merchant
from app.pipeline.types import ClassificationReport, Flow, Holding


def _dt(s: str) -> datetime:
    return datetime.strptime(s[:14].ljust(14, "0"), "%Y%m%d%H%M%S")


def _num(v) -> float:
    return float(v or 0)


# ===========================================================================
# 자산 · 부채 (구조화 코드 기준)
# ===========================================================================
def classify_holdings(data: Dict[str, dict]) -> List[Holding]:
    holdings: List[Holding] = []

    # --- 은행 수신: 계좌유형 코드 → 현금성 / 저축성 (D-08), 상품명은 모호할 때만 보조
    bank = data.get("bank_accounts", {})
    accounts = {a["account_num"]: a for a in bank.get("account_list", [])}
    for d in bank.get("detail_list", []):
        acc = accounts.get(d["account_num"], {})
        kind_sub = BANK_ACCOUNT_TYPE.get(acc.get("account_type"))
        if kind_sub is None:
            name = (acc.get("prod_name") or "").casefold()
            kind_sub = next((v for k, v in BANK_NAME_FALLBACK if k in name), ("cash", "기타수신"))
        kind, sub = kind_sub
        eligible = kind == "cash" and not acc.get("is_foreign_deposit", False)  # D-06
        holdings.append(Holding("asset", kind, sub, acc.get("prod_name", sub),
                                _num(d.get("balance_amt")), emergency_eligible=eligible))

    # --- 전자금융(페이머니): 현금성이지만 비상금에서는 제외 (D-06)
    for b in data.get("efin_accounts", {}).get("balance_list", []):
        holdings.append(Holding("asset", "cash", "페이머니", b.get("account_id", "페이머니"),
                                _num(b.get("balance_amt")), emergency_eligible=False))

    # --- 금융투자: 예수금 + 보유 상품 평가액
    invest = data.get("invest_accounts", {})
    for b in invest.get("basic_list", []):
        if _num(b.get("withholdings_amt")) > 0:
            holdings.append(Holding("asset", "invest", "예수금", b.get("account_num", ""),
                                    _num(b.get("withholdings_amt"))))
    for p in invest.get("product_list", []):
        sub = INVEST_PROD_TYPE.get(p.get("prod_type"), "기타투자")
        holdings.append(Holding("asset", "invest", sub, p.get("prod_name", sub),
                                _num(p.get("eval_amt"))))

    # --- 연금: IRP 평가액
    for d in data.get("irp_accounts", {}).get("detail_list", []):
        holdings.append(Holding("asset", "pension", "IRP", d.get("irp_prod_name", "IRP"),
                                _num(d.get("eval_amt"))))

    # --- 부채: 상환방식·계좌유형 코드 1차, 상품명 보조
    for key in ("bank_loans", "capital_loans"):
        payload = data.get(key, {})
        loans = {l["account_num"]: l for l in payload.get("loan_list", [])}
        for d in payload.get("detail_list", []):
            ln = loans.get(d["account_num"], {})
            kind, sub = _classify_loan(ln)
            holdings.append(Holding("liability", kind, sub, ln.get("prod_name", sub),
                                    _num(d.get("balance_amt"))))

    card_loans = data.get("card_loans", {})
    for r in card_loans.get("revolving_list", []):
        holdings.append(Holding("liability", "other", "리볼빙", "카드 리볼빙", _num(r.get("remain_amt"))))
    for s in card_loans.get("short_term_list", []):
        holdings.append(Holding("liability", "other", "현금서비스", "카드 현금서비스", _num(s.get("remain_amt"))))
    for l in card_loans.get("long_term_list", []):
        holdings.append(Holding("liability", "other", "카드론", "카드론", _num(l.get("remain_amt"))))

    return [h for h in holdings if h.amount > 0]


def _classify_loan(loan: dict) -> Tuple[str, str]:
    code = str(loan.get("account_type", ""))
    for prefix, kind_sub in LOAN_TYPE_PREFIX:
        if code.startswith(prefix):
            kind, sub = kind_sub
            name = (loan.get("prod_name") or "")
            for kw, (k2, s2) in LOAN_NAME_FALLBACK:     # 세분류는 상품명 보조
                if kw in name:
                    return kind, s2
            return kind, sub
    name = loan.get("prod_name") or ""
    for kw, kind_sub in LOAN_NAME_FALLBACK:
        if kw in name:
            return kind_sub
    return ("unsecured", "신용대출")


# ===========================================================================
# 입출금·결제 흐름 (수입 / 고정지출 / 변동지출 / 저축·투자 / 이체)
# ===========================================================================
_IN_CLASSES = {"급여", "입금"}
_IN_TYPES = {"01", "03"}   # 테스트 데이터 규약: 03 = 급여 입금. 실연동 시 규격의 입출금 구분으로 교체


def _bank_direction(tr: dict) -> str:
    if tr.get("trans_class") in _IN_CLASSES or tr.get("trans_type") in _IN_TYPES:
        return "in"
    return "out"


def classify_flows(
    data: Dict[str, dict],
    merchant: MerchantClassifier,
) -> Tuple[List[Flow], ClassificationReport]:
    flows: List[Flow] = []

    flows += _bank_flows(data.get("bank_transactions", {}), merchant)
    flows += _card_flows(data.get("card_approvals", {}), merchant)
    flows += _efin_flows(data.get("efin_accounts", {}), merchant)

    months = _months_covered(flows)
    max_day = max((f.occurred_on for f in flows), default=None)
    flows += _telecom_flows(data.get("telecom_contracts", {}))
    flows += _insurance_flows(data.get("insurance_list", {}), months, max_day)
    flows += _loan_flows(data.get("bank_loans", {}))
    flows += _loan_flows(data.get("capital_loans", {}))
    flows += _saving_flows(data.get("invest_accounts", {}), data.get("irp_accounts", {}))

    _apply_recurrence(flows)

    report = ClassificationReport(total=len(flows), llm_calls=merchant.llm_calls)
    report.by_stage = dict(Counter(f.stage for f in flows))
    report.needs_review = sum(1 for f in flows if f.needs_review)
    return flows, report


# ---------------------------------------------------------------- 은행
def _bank_flows(payload: dict, merchant: MerchantClassifier) -> List[Flow]:
    out: List[Flow] = []
    for tr in payload.get("trans_list", []):
        day = _dt(tr["trans_dtime"]).date()
        amt = _num(tr.get("trans_amt"))
        memo = (tr.get("trans_memo") or "").strip()
        if amt <= 0:
            continue

        if _bank_direction(tr) == "in":
            sub, stage, rule = "비정기수입", 2, "default"
            for kw, label in INCOME_KEYWORDS:
                if kw in memo:
                    sub, stage, rule = label, 2, "memo_keyword"
                    break
            else:
                stage = 4 if not memo else 2
            out.append(Flow(day, amt, "in", "bank", memo or "(적요 없음)", "income", sub,
                            stage=stage, rule=rule, needs_review=not memo))
            continue

        # ---- 출금
        if any(k in memo for k in CARD_BILL_KEYWORDS):
            out.append(Flow(day, amt, "out", "bank", memo, "transfer", "카드대금", 1, "card_bill"))
        elif any(k in memo for k in SAVING_TRANSFER_KEYWORDS):
            out.append(Flow(day, amt, "out", "bank", memo, "saving", "저축·투자", 2, "memo_keyword"))
        elif any(k in memo for k in DEDICATED_SOURCE_KEYWORDS):
            # 보험·통신·대출은 전용 API에서 집계 → 은행 출금은 중복 방지로 제외
            out.append(Flow(day, amt, "out", "bank", memo, "ignored", "전용API중복", 1, "dedup"))
        else:
            res = merchant.classify(memo)
            major = major_for_category(res.category) if res.category != UNCLASSIFIED else "variable"
            out.append(Flow(day, amt, "out", "bank", memo or "(적요 없음)", major, res.category,
                            res.stage, res.rule, res.confidence, res.needs_review))
    return out


# ---------------------------------------------------------------- 카드
def _card_flows(payload: dict, merchant: MerchantClassifier) -> List[Flow]:
    out: List[Flow] = []
    for ap in payload.get("approved_list", []):
        if ap.get("status") != "01":        # 승인 건만 (취소·정정 제외)
            continue
        day = _dt(ap["approved_dtime"]).date()
        name = ap.get("merchant_name") or ""
        res = merchant.classify(name)
        major = major_for_category(res.category) if res.category != UNCLASSIFIED else "variable"
        out.append(Flow(day, _num(ap.get("approved_amt")), "out", "card", name or "(가맹점명 없음)",
                        major, res.category, res.stage, res.rule, res.confidence, res.needs_review))
    return out


# ---------------------------------------------------------------- 전자금융
def _efin_flows(payload: dict, merchant: MerchantClassifier) -> List[Flow]:
    """페이 결제만 소비로 집계한다(충전은 계좌↔페이 이동이므로 제외)."""
    out: List[Flow] = []
    for tr in payload.get("trans_list", []):
        if tr.get("trans_type") != "02":
            continue
        day = _dt(tr["trans_dtime"]).date()
        name = tr.get("merchant_name") or ""
        res = merchant.classify(name)
        major = major_for_category(res.category) if res.category != UNCLASSIFIED else "variable"
        out.append(Flow(day, _num(tr.get("trans_amt")), "out", "efin", name or "(가맹점명 없음)",
                        major, res.category, res.stage, res.rule, res.confidence, res.needs_review))
    return out


# ---------------------------------------------------------------- 통신·보험·대출 (전용 API)
def _telecom_flows(payload: dict) -> List[Flow]:
    return [
        Flow(_dt(p["paid_dtime"]).date(), _num(p.get("paid_amt")), "out", "telecom", "통신요금",
             "fixed", "통신", 1, "source_api")
        for p in payload.get("paid_list", [])
        if _num(p.get("paid_amt")) > 0
    ]


def _insurance_flows(payload: dict, months: List[Tuple[int, int]], max_day: Optional[date]) -> List[Flow]:
    """보험료 납입: 월납(pay_cycle=1M) 계약을 관측 기간의 각 월 납입일로 전개한다."""
    names = {i["insu_num"]: i.get("prod_name", "보험") for i in payload.get("insu_list", [])}
    out: List[Flow] = []
    for p in payload.get("payment_list", []):
        if p.get("pay_cycle") != "1M" or _num(p.get("pay_amt")) <= 0:
            continue
        for (y, m) in months:
            last = calendar.monthrange(y, m)[1]
            day = date(y, m, min(int(p.get("pay_date") or 1), last))
            if max_day and day > max_day:
                continue
            out.append(Flow(day, _num(p.get("pay_amt")), "out", "insurance",
                            names.get(p.get("insu_num"), "보험료"), "fixed", "보험", 1, "source_api"))
    return out


def _loan_flows(payload: dict) -> List[Flow]:
    return [
        Flow(_dt(t["trans_dtime"]).date(), _num(t.get("trans_amt")), "out", "loan", "대출 원리금",
             "fixed", "대출상환", 1, "source_api")
        for t in payload.get("trans_list", [])
        if _num(t.get("trans_amt")) > 0
    ]


def _saving_flows(invest: dict, irp: dict) -> List[Flow]:
    """증권 매수·IRP 납입은 지출이 아닌 저축·투자 납입액이다 (D-01: 당월 신규 납입액)."""
    out: List[Flow] = []
    for t in invest.get("trans_list", []):
        if t.get("trans_type") == "01" and _num(t.get("trans_amt")) > 0:   # 매수
            out.append(Flow(_dt(t["trans_dtime"]).date(), _num(t.get("trans_amt")), "out", "invest",
                            t.get("trans_type_detail") or "증권 매수", "saving", "저축·투자", 1, "source_api"))
    for t in irp.get("trans_list", []):
        if t.get("trans_type") == "01" and _num(t.get("trans_amt")) > 0:   # 납입
            out.append(Flow(_dt(t["trans_dtime"]).date(), _num(t.get("trans_amt")), "out", "irp",
                            "IRP 납입", "saving", "저축·투자", 1, "source_api"))
    return out


def _months_covered(flows: Iterable[Flow]) -> List[Tuple[int, int]]:
    days = sorted(f.occurred_on for f in flows)
    if not days:
        return []
    y, m = days[0].year, days[0].month
    end = (days[-1].year, days[-1].month)
    months = []
    while (y, m) <= end:
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


# ---------------------------------------------------------------- 주기성 적용
def _apply_recurrence(flows: List[Flow]) -> None:
    """수입은 정기수입 판별, 지출은 주기성 있는 건을 고정지출로 승격한다.

    - 수입: 적요 키워드 + 주기성(월 1회, ±3일, 금액 일정)이 모두 맞으면 '정기수입'
    - 지출: 가맹점/적요별로 ±3일·금액 ±10%(공과금·통신 ±30%)·3회 이상이면 고정지출
    """
    # 수입
    inc = [f for f in flows if f.major == "income"]
    rec = detect_recurring(
        (Occurrence(normalize_merchant(f.counterparty), f.occurred_on, f.amount) for f in inc),
        amount_tol=params.AMOUNT_TOL_FIXED,
    )
    for f in inc:
        if normalize_merchant(f.counterparty) in rec:
            f.recurring = True
            if f.category == "비정기수입":     # 키워드가 없어도 주기성이 확인되면 정기수입
                f.category = "정기수입"
                f.rule = "recurrence"

    # 지출: 이미 고정으로 확정된 것(전용 API·고정 카테고리)과 이체·저축은 제외하고 변동 후보만 검사
    var = [f for f in flows if f.major == "variable" and f.direction == "out"]
    groups: Dict[bool, List[Flow]] = {True: [], False: []}
    for f in var:
        groups[f.category in UTILITY_LIKE_CATEGORIES].append(f)
    for utility, items in groups.items():
        tol = params.AMOUNT_TOL_UTILITY if utility else params.AMOUNT_TOL_FIXED
        rec = detect_recurring(
            (Occurrence(normalize_merchant(f.counterparty), f.occurred_on, f.amount) for f in items),
            amount_tol=tol,
        )
        for f in items:
            if normalize_merchant(f.counterparty) in rec and f.counterparty:
                f.major = "fixed"
                f.recurring = True
    # 고정 카테고리(구독·공과금·주거 등)는 카테고리만으로도 recurring 표시
    for f in flows:
        if f.major == "fixed":
            f.recurring = True
