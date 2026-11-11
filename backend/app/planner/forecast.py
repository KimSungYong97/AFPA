"""월중 현금 전망 — 이번 달 소비 속도로 월말까지 가면 어떻게 되는지 코드로 계산한다

입력은 분류된 거래와 현재 현금성 자산뿐이며 LLM은 쓰지 않는다. 방법:
- 변동지출: 카테고리별로 '지금까지 쓴 속도'와 '평소(최근 완결 월 평균)'를 경과 일수 비율로 섞어 월말 예상액을 구한다.
  (초반에는 평소 값에 가깝게, 월 후반일수록 이번 달 속도에 가깝게)
- 고정지출·저축 이체·정기수입: 최근 달들의 지급일(중앙값)과 금액으로 아직 안 나간/안 들어온 것을 미래 일정으로 놓는다.
- 하루씩 현금 잔액을 굴려 월중 최저 현금과 날짜, 월말 잔액을 구한다.
판정: 현금이 0 아래로 내려가면 danger, 지출 초과나 현금 부족 근접이면 watch, 아니면 ok.
"""
import calendar
import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional

from app.pipeline import params
from app.pipeline.engines import observation_window
from app.pipeline.types import Flow


def _recurring_schedule(flows: List[Flow], window_months: set, major: str, direction: str,
                        month: tuple, as_of: date) -> List[dict]:
    """정기 항목(고정지출·정기수입·저축 이체)의 이번 달 남은 일정"""
    by_cp: Dict[str, List[Flow]] = defaultdict(list)
    for f in flows:
        if f.major == major and f.direction == direction and f.recurring \
                and (f.occurred_on.year, f.occurred_on.month) in window_months:
            by_cp[f.counterparty].append(f)
    dim = calendar.monthrange(*month)[1]
    out = []
    for name, rows in by_cp.items():
        if len({(r.occurred_on.year, r.occurred_on.month) for r in rows}) < 2:
            continue                                         # 두 달 이상 보인 것만 정기로 본다
        day = int(statistics.median(r.occurred_on.day for r in rows))
        amount = statistics.median(r.amount for r in rows)
        done = any((f.occurred_on.year, f.occurred_on.month) == month and f.counterparty == name
                   and f.major == major and f.direction == direction and f.occurred_on <= as_of for f in flows)
        if done:
            continue
        due = date(month[0], month[1], min(day, dim))
        late = due <= as_of                                  # 지급일이 지났는데 아직 안 보임
        if late and major == "income":
            continue                                         # 못 받은 수입은 보수적으로 넣지 않는다
        out.append({"name": name, "date": max(due, as_of + timedelta(days=1)), "amount": round(amount), "late": late})
    return out


def forecast(as_of: date, flows: List[Flow], liquid_cash: float, monthly_income: Optional[float] = None) -> dict:
    window, partial = observation_window(as_of, flows)
    month = (as_of.year, as_of.month)
    dim = calendar.monthrange(*month)[1]
    elapsed, remaining = as_of.day, dim - as_of.day
    base = {"month": f"{month[0]}-{month[1]:02d}", "as_of": as_of.isoformat()}
    if partial or not window:
        return {**base, "status": "insufficient_history", "risk": "ok",
                "note": "비교할 완결된 달이 없어 월중 전망을 만들 수 없어요."}
    if remaining <= 0:
        return {**base, "status": "month_end", "risk": "ok", "note": "이번 달 마지막 날이라 전망할 구간이 없어요."}

    wset = set(window)
    cat_base: Dict[str, float] = defaultdict(float)
    cat_so_far: Dict[str, float] = defaultdict(float)
    for f in flows:
        if f.major != "variable" or f.direction != "out":
            continue
        ym = (f.occurred_on.year, f.occurred_on.month)
        if ym in wset:
            cat_base[f.category] += f.amount / len(window)
        elif ym == month and f.occurred_on <= as_of:
            cat_so_far[f.category] += f.amount

    w = elapsed / dim
    cats = []
    for c in set(cat_base) | set(cat_so_far):
        b, s = cat_base.get(c, 0.0), cat_so_far.get(c, 0.0)
        pace = s / elapsed * dim
        proj = max(w * pace + (1 - w) * b, s)
        cats.append({"category": c, "so_far": round(s), "projected": round(proj), "baseline": round(b)})
    spent = sum(c["so_far"] for c in cats)
    projected = sum(c["projected"] for c in cats)
    baseline = sum(c["baseline"] for c in cats)
    income = monthly_income or 0
    over = []
    for c in cats:
        diff = c["projected"] - c["baseline"]
        if c["baseline"] > 0 and c["projected"] >= c["baseline"] * (1 + params.OUTLIER_GROWTH) \
                and diff >= max(income * params.OUTLIER_MIN_INCOME_SHARE, 10_000):
            over.append({**c, "over": round(diff), "over_pct": round(diff / c["baseline"] * 100)})
    over.sort(key=lambda x: -x["over"])

    fixed = _recurring_schedule(flows, wset, "fixed", "out", month, as_of)
    saving = _recurring_schedule(flows, wset, "saving", "out", month, as_of)
    incomes = _recurring_schedule(flows, wset, "income", "in", month, as_of)
    events = ([{**x, "kind": "고정지출"} for x in fixed] + [{**x, "kind": "저축·투자 이체"} for x in saving]
              + [{**x, "kind": "수입"} for x in incomes])

    cash, lo, lo_date = liquid_cash, liquid_cash, as_of
    daily_var = max(projected - spent, 0) / remaining
    for i in range(1, remaining + 1):
        d = as_of + timedelta(days=i)
        cash -= daily_var
        for e in events:
            if e["date"] == d:
                cash += e["amount"] if e["kind"] == "수입" else -e["amount"]
        if cash < lo:
            lo, lo_date = cash, d
    end_cash = cash

    fixed_monthly = sum(
        f.amount for f in flows if f.major == "fixed" and f.direction == "out" and f.recurring
        and (f.occurred_on.year, f.occurred_on.month) in wset) / len(window)
    overspend = projected - baseline
    if lo < 0:
        risk = "danger"
    elif (baseline > 0 and projected >= baseline * (1 + params.F_OVERSPEND_RATIO)
          and overspend >= max(income * params.OUTLIER_MIN_INCOME_SHARE, 10_000)) \
            or (fixed_monthly > 0 and lo < fixed_monthly * params.F_LOW_CASH_FIXED_RATIO):
        risk = "watch"
    else:
        risk = "ok"
    return {**base, "status": "ok", "risk": risk, "days_elapsed": elapsed, "days_in_month": dim,
            "spent_so_far": round(spent), "projected_variable": round(projected), "baseline_variable": round(baseline),
            "overspend": round(overspend), "categories": sorted(cats, key=lambda c: -c["projected"])[:8],
            "overspent_categories": over[:params.F_TOP_CATEGORIES],
            "upcoming": sorted(({"date": e["date"].isoformat(), "name": e["name"], "amount": e["amount"], "kind": e["kind"],
                                 "late": e.get("late", False)} for e in events), key=lambda e: e["date"]),
            "cash_now": round(liquid_cash), "min_cash": round(lo), "min_cash_date": lo_date.isoformat(),
            "end_cash": round(end_cash)}
