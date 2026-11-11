"""금융 프로필 6개 엔진 (분류된 데이터 → 정량 지표)

「금융 프로필 산출 로직」 구현. 모든 계산은 결정적(코드)이며 LLM을 사용하지 않는다.
  1 현금 흐름 / 2 자산·부채 건전성 / 3 비상금 충당 / 4 소비 진단 / 5 금융 건강도 / 6 금융 잠재력

결측 처리: 월 총수입을 알 수 없으면 비율 지표와 종합 점수는 NULL(None)로 두고 0으로 강제하지 않는다 (D-03).
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

from app.pipeline import params
from app.pipeline.types import Flow, GoalInfo, Holding, OnboardingInfo

Month = Tuple[int, int]


# ===========================================================================
# 입력 / 출력
# ===========================================================================
@dataclass
class EngineInput:
    as_of: date
    flows: List[Flow]
    holdings: List[Holding]
    onboarding: OnboardingInfo = field(default_factory=OnboardingInfo)
    goals: List[GoalInfo] = field(default_factory=list)


@dataclass
class EngineResult:
    monthly_income_net: Optional[float]
    savings_ratio: Optional[float]
    dsr_ratio: Optional[float]
    emergency_fund_ratio: Optional[float]
    consumption_ratio: Optional[float]
    health_score: Optional[float]
    potential_score: Optional[float]
    net_cash_flow: Optional[float]
    net_worth: float
    debt_ratio: Optional[float]
    details: dict


# ===========================================================================
# 유틸
# ===========================================================================
def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _r(x: Optional[float], n: int = 1) -> Optional[float]:
    return None if x is None else round(x, n)


def _month(d: date) -> Month:
    return (d.year, d.month)


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def observation_window(as_of: date, flows: List[Flow]) -> Tuple[List[Month], bool]:
    """관측 개월 목록과 '진행 중인 달만 있는 경우' 여부.

    완결된 달(as_of가 속한 달 이전)을 최근 6개월까지 사용한다(P-04).
    완결된 달이 하나도 없으면 진행 중인 달을 쓰되 partial=True로 표시한다.
    """
    present = sorted({_month(f.occurred_on) for f in flows if f.occurred_on <= as_of})
    complete = [m for m in present if m < _month(as_of)]
    if complete:
        return complete[-params.WINDOW_MONTHS_MAX:], False
    return present[-1:], True


def _monthly_avg(flows: List[Flow], window: List[Month]) -> float:
    if not window:
        return 0.0
    ws = set(window)
    return sum(f.amount for f in flows if _month(f.occurred_on) in ws) / len(window)


def _by_month(flows: List[Flow], window: List[Month]) -> Dict[Month, float]:
    out: Dict[Month, float] = {m: 0.0 for m in window}
    for f in flows:
        m = _month(f.occurred_on)
        if m in out:
            out[m] += f.amount
    return out


def _age(birth: Optional[date], as_of: date) -> Optional[int]:
    if birth is None:
        return None
    return as_of.year - birth.year - ((as_of.month, as_of.day) < (birth.month, birth.day))


def grade(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    for threshold, g in params.GRADES:
        if score >= threshold:
            return g
    return "E"


# ===========================================================================
# 메인
# ===========================================================================
def compute(inp: EngineInput) -> EngineResult:
    window, partial = observation_window(inp.as_of, inp.flows)
    quality: List[str] = []
    if partial:
        quality.append("완결된 달이 없어 진행 중인 달 기준으로 산출")
    elif len(window) < params.WINDOW_MONTHS_MIN:
        quality.append(f"관측 기간 {len(window)}개월 (권장 {params.WINDOW_MONTHS_MIN}개월 이상)")

    cash = _cash_flow(inp, window, quality)
    bs = _balance_sheet(inp, window, cash)
    em = _emergency(inp, window, cash)
    sp = _spending(inp, window, cash)
    health = _health(cash, bs, em, sp, inp.flows, window)
    potential = _potential(inp, window, cash)

    details = {
        "window_months": [f"{y}-{m:02d}" for y, m in window],
        "data_quality": quality,
        "cash_flow": cash,
        "balance_sheet": bs,
        "emergency_fund": em,
        "spending": sp,
        "health": health,
        "potential": potential,
    }
    return EngineResult(
        monthly_income_net=cash["monthly_income"],
        savings_ratio=health["metrics"]["savings_ratio"],
        dsr_ratio=bs["dsr_ratio"],
        emergency_fund_ratio=em["coverage_ratio"],
        consumption_ratio=sp["consumption_ratio"],
        health_score=health["score"],
        potential_score=potential["score"],
        net_cash_flow=cash["net_cash_flow"],
        net_worth=bs["net_worth"],
        debt_ratio=bs["debt_ratio"],
        details=details,
    )


# ===========================================================================
# 1. 현금 흐름 엔진
# ===========================================================================
def _cash_flow(inp: EngineInput, window: List[Month], quality: List[str]) -> dict:
    income_flows = [f for f in inp.flows if f.major == "income"]
    regular = [f for f in income_flows if f.recurring]

    # D-03: 정기수입이 파악되면 그 평균, 아니면 최근 3개월 입금 평균, 그마저 없으면 NULL
    reg_by_month = _by_month(regular, window)
    reg_months = sum(1 for v in reg_by_month.values() if v > 0)
    income: Optional[float]
    basis: str
    if regular and reg_months >= min(params.WINDOW_MONTHS_MIN, len(window)):
        income = sum(reg_by_month.values()) / len(window)
        basis = "정기수입 평균"
    else:
        recent = window[-params.WINDOW_MONTHS_MIN:]
        total = sum(_by_month(income_flows, recent).values())
        income = total / len(recent) if recent and total > 0 else None
        basis = "최근 3개월 입금 평균" if income is not None else "산출 불가"
        if income is not None:
            quality.append("정기수입을 확인하지 못해 최근 3개월 입금 평균으로 대체")
        else:
            quality.append("수입 데이터가 없어 비율 지표 산출 보류")

    fixed = [f for f in inp.flows if f.major == "fixed" and f.direction == "out"]
    variable = [f for f in inp.flows if f.major == "variable" and f.direction == "out"]
    fixed_avg = _monthly_avg(fixed, window)
    variable_avg = _monthly_avg(variable, window)

    return {
        "monthly_income": _r(income, 0),
        "income_basis": basis,
        "fixed_expense": _r(fixed_avg, 0),
        "variable_expense": _r(variable_avg, 0),
        # 월 가용 소득(내부 중간값) / 월 여유 자금(노출 대표 지표, D-02)
        "monthly_disposable": _r(income - fixed_avg, 0) if income is not None else None,
        "net_cash_flow": _r(income - fixed_avg - variable_avg, 0) if income is not None else None,
    }


# ===========================================================================
# 2. 자산·부채 건전성 엔진
# ===========================================================================
def _balance_sheet(inp: EngineInput, window: List[Month], cash: dict) -> dict:
    assets = [h for h in inp.holdings if h.side == "asset"]
    debts = [h for h in inp.holdings if h.side == "liability"]
    total_assets = sum(h.amount for h in assets)
    total_debt = sum(h.amount for h in debts)

    by_kind: Dict[str, float] = defaultdict(float)
    for h in assets:
        by_kind[h.kind] += h.amount
    mix = {k: _r(v / total_assets * 100) for k, v in by_kind.items()} if total_assets > 0 else {}

    repay_flows = [f for f in inp.flows if f.category == "대출상환"]
    monthly_repay = _monthly_avg(repay_flows, window)
    income = cash["monthly_income"]
    dsr = monthly_repay / income * 100 if income else None
    debt_ratio = total_debt / total_assets * 100 if total_assets > 0 else None

    return {
        "total_assets": _r(total_assets, 0),
        "total_debt": _r(total_debt, 0),
        "net_worth": _r(total_assets - total_debt, 0),
        "assets_by_kind": {k: _r(v, 0) for k, v in by_kind.items()},
        "liquidity_mix_pct": mix,
        "monthly_debt_service": _r(monthly_repay, 0),
        # 모든 대출 원리금을 분자로 하므로 DTI가 아닌 DSR (D-07)
        "dsr_ratio": _r(dsr, 2),
        "debt_ratio": _r(debt_ratio, 2),
    }


# ===========================================================================
# 3. 비상금 충당 엔진
# ===========================================================================
def _emergency(inp: EngineInput, window: List[Month], cash: dict) -> dict:
    essential_var = _monthly_avg(
        [f for f in inp.flows if f.major == "variable" and f.direction == "out"
         and f.category in params.ESSENTIAL_VARIABLE_CATEGORIES],
        window,
    )
    essential = (cash["fixed_expense"] or 0) + essential_var
    irregular = inp.onboarding.employment_status in ("FREELANCER", "SELF_EMPLOYED")
    months = params.EMERGENCY_MONTHS_IRREGULAR if irregular else params.EMERGENCY_MONTHS_DEFAULT
    required = essential * months
    # D-06: 입출금·CMA만 인정 (페이머니·외화·정기예금 제외)
    liquid = sum(h.amount for h in inp.holdings
                 if h.side == "asset" and h.emergency_eligible)
    coverage = liquid / required * 100 if required > 0 else None
    return {
        "monthly_essential_expense": _r(essential, 0),
        "months": months,
        "required": _r(required, 0),
        "liquid_cash": _r(liquid, 0),
        "coverage_ratio": _r(coverage, 2),
    }


# ===========================================================================
# 4. 소비 진단 엔진
# ===========================================================================
def _spending(inp: EngineInput, window: List[Month], cash: dict) -> dict:
    income = cash["monthly_income"]
    total_spend = (cash["fixed_expense"] or 0) + (cash["variable_expense"] or 0)
    consumption = total_spend / income * 100 if income else None

    variable = [f for f in inp.flows if f.major == "variable" and f.direction == "out"]
    cat_total: Dict[str, float] = defaultdict(float)
    ws = set(window)
    for f in variable:
        if _month(f.occurred_on) in ws:
            cat_total[f.category] += f.amount
    var_sum = sum(cat_total.values())
    shares = {c: _r(v / var_sum * 100) for c, v in sorted(cat_total.items(), key=lambda x: -x[1])} \
        if var_sum > 0 else {}

    # 이상 지출 (P-05): 최근 완결월이 직전 3개월 평균 대비 +20% 이상, 증가액이 월 소득의 1% 이상
    outliers: List[dict] = []
    if len(window) >= 4 and income:
        recent_m, base_ms = window[-1], window[-4:-1]
        for cat in cat_total:
            rows = [f for f in variable if f.category == cat]
            recent = sum(f.amount for f in rows if _month(f.occurred_on) == recent_m)
            base = sum(f.amount for f in rows if _month(f.occurred_on) in set(base_ms)) / 3
            if base > 0 and recent >= base * (1 + params.OUTLIER_GROWTH) \
                    and (recent - base) >= income * params.OUTLIER_MIN_INCOME_SHARE:
                outliers.append({
                    "category": cat, "recent": _r(recent, 0), "baseline": _r(base, 0),
                    "growth_pct": _r((recent / base - 1) * 100),
                })
    elif len(window) < 4:
        outliers = []

    return {
        "consumption_ratio": _r(consumption, 2),
        "category_share_pct": shares,
        "outliers": sorted(outliers, key=lambda o: -(o["recent"] - o["baseline"])),
        "outlier_note": None if len(window) >= 4 else "관측 기간이 짧아 이상 지출 판정 보류",
    }


# ===========================================================================
# 5. 금융 건강도 (현황, 100점)
# ===========================================================================
def _piecewise_down(x: float, full_below: float, zero_at: float) -> float:
    """full_below 이하 1.0 → zero_at 이상 0.0 (선형 감소)"""
    if x <= full_below:
        return 1.0
    if x >= zero_at:
        return 0.0
    return 1.0 - (x - full_below) / (zero_at - full_below)


def _spend_curve(ratio: float) -> float:
    if ratio <= params.SPEND_FULL_BELOW:
        return 1.0
    if ratio <= params.SPEND_HALF_AT:
        return 1.0 - 0.5 * (ratio - params.SPEND_FULL_BELOW) / (params.SPEND_HALF_AT - params.SPEND_FULL_BELOW)
    if ratio >= params.SPEND_ZERO_AT:
        return 0.0
    return 0.5 * (1 - (ratio - params.SPEND_HALF_AT) / (params.SPEND_ZERO_AT - params.SPEND_HALF_AT))


def _health(cash: dict, bs: dict, em: dict, sp: dict, flows: List[Flow], window: List[Month]) -> dict:
    income = cash["monthly_income"]
    saving_monthly = _monthly_avg([f for f in flows if f.major == "saving"], window)   # D-01
    metrics = {
        "monthly_saving": _r(saving_monthly, 0),
        "savings_ratio": _r(saving_monthly / income * 100, 2) if income else None,
    }
    if not income:
        return {"score": None, "grade": None, "components": {}, "metrics": metrics,
                "note": "월 수입을 알 수 없어 점수 산출 보류"}

    w = params.HEALTH_WEIGHTS
    comps: Dict[str, Optional[float]] = {}
    comps["saving"] = _clamp(saving_monthly / income / params.SAVING_TARGET_RATIO)
    comps["debt"] = _piecewise_down(bs["dsr_ratio"] or 0.0, params.DSR_FULL_BELOW, params.DSR_ZERO_AT)
    comps["emergency"] = _clamp((em["coverage_ratio"] or 0) / 100) if em["coverage_ratio"] is not None else None
    comps["spending"] = _spend_curve((cash["variable_expense"] or 0) / income)

    avail = {k: v for k, v in comps.items() if v is not None}
    wsum = sum(w[k] for k in avail)
    score = sum(avail[k] * w[k] for k in avail) / wsum * 100 if wsum else None
    return {
        "score": _r(score),
        "grade": grade(score),
        "components": {k: {"weight": w[k], "ratio": _r(v, 3), "points": _r(v * w[k])}
                       for k, v in avail.items()},
        "metrics": metrics,
    }


# ===========================================================================
# 6. 금융 잠재력 (전망, 100점)
# ===========================================================================
_EMPLOYMENT_BASE = {"FULL_TIME": 0.6, "FREELANCER": 0.5, "SELF_EMPLOYED": 0.5, "UNEMPLOYED": 0.2}


def _potential(inp: EngineInput, window: List[Month], cash: dict) -> dict:
    income = cash["monthly_income"]
    if not income:
        return {"score": None, "kind": None, "components": {}, "goals": [],
                "note": "월 수입을 알 수 없어 점수 산출 보류"}

    surplus = max(cash["net_cash_flow"] or 0, 0.0)
    comps: Dict[str, Optional[float]] = {}

    # (1) 목표 진척 속도: 1차 단순 배분 가정 — 월 여유 자금을 우선순위 순으로 각 목표의 필요 월 저축액에 채움
    goal_rows, velocity = _goal_velocity(inp, surplus)
    comps["velocity"] = velocity

    # (2) 저축 여력
    comps["surplus"] = _clamp(surplus / income / params.SURPLUS_TARGET_RATIO)

    # (3) 소득 성장성: 소득 추세 + 나이·고용형태 보정
    comps["income_growth"], growth_info = _income_growth(inp, window)

    # (4) 시간 여유
    comps["horizon"], horizon_years = _horizon(inp, goal_rows)

    w = params.POTENTIAL_WEIGHTS
    avail = {k: v for k, v in comps.items() if v is not None}
    wsum = sum(w[k] for k in avail)
    score = sum(avail[k] * w[k] for k in avail) / wsum * 100
    return {
        "score": _r(score),
        "kind": "full" if velocity is not None else "basic",   # 목표 미설정 시 기초 잠재력
        "components": {k: {"weight": w[k], "ratio": _r(v, 3), "points": _r(v * w[k])}
                       for k, v in avail.items()},
        "goals": goal_rows,
        "income_growth": growth_info,
        "horizon_years": _r(horizon_years),
    }


def _goal_velocity(inp: EngineInput, surplus: float) -> Tuple[List[dict], Optional[float]]:
    rows: List[dict] = []
    remaining_pool = surplus
    for g in sorted(inp.goals, key=lambda g: g.priority):
        remaining = max(g.target_amount - g.current_amount, 0.0)
        if remaining <= 0:
            continue
        if g.target_date is None:
            rows.append({"name": g.name, "remaining": _r(remaining, 0), "required_monthly": None,
                         "allocated": None, "years_left": None})
            continue
        months_left = max(_months_between(inp.as_of, g.target_date), 1)
        required = remaining / months_left
        alloc = min(remaining_pool, required)
        remaining_pool -= alloc
        rows.append({
            "name": g.name, "remaining": _r(remaining, 0), "months_left": months_left,
            "required_monthly": _r(required, 0), "allocated": _r(alloc, 0),
            "velocity_raw": _r(alloc * 12 / remaining, 3),            # (월 배분액×12)/남은 금액
            "coverage": _r(alloc / required, 3),
            "years_left": _r(months_left / 12),
        })
    scored = [(r["remaining"], r["coverage"]) for r in rows if r.get("coverage") is not None]
    if not scored:
        return rows, None
    total = sum(w for w, _ in scored)
    return rows, sum(w * c for w, c in scored) / total


def _income_growth(inp: EngineInput, window: List[Month]) -> Tuple[float, dict]:
    emp = inp.onboarding.employment_status
    base = _EMPLOYMENT_BASE.get(emp, 0.5)
    age = _age(inp.onboarding.birth_date, inp.as_of)
    if age is not None:
        base += 0.2 if age < 30 else 0.1 if age < 40 else 0.0 if age < 50 else -0.1 if age < 60 else -0.2
    base = _clamp(base)

    trend: Optional[float] = None
    growth: Optional[float] = None
    if len(window) >= 6:
        series = _by_month([f for f in inp.flows if f.major == "income" and f.recurring], window)
        vals = [series[m] for m in window]
        first, last = sum(vals[:3]) / 3, sum(vals[-3:]) / 3
        if first > 0:
            growth = last / first - 1
            trend = _clamp(0.5 + growth * 5)
    value = base if trend is None else 0.5 * base + 0.5 * trend
    return value, {"employment": emp, "age": age, "growth_6m": _r(growth, 3),
                   "basis": "추세+보정" if trend is not None else "나이·고용형태 보정"}


def _horizon(inp: EngineInput, goal_rows: List[dict]) -> Tuple[float, float]:
    dated = [(r["remaining"], r["years_left"]) for r in goal_rows if r.get("years_left") is not None]
    if dated:
        total = sum(w for w, _ in dated)
        years = sum(w * y for w, y in dated) / total
    else:
        age = _age(inp.onboarding.birth_date, inp.as_of)
        years = max(60 - age, 0) if age is not None else params.NO_DATE_GOAL_YEARS
    return _clamp(years / params.HORIZON_FULL_YEARS), years
