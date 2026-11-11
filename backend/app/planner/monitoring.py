"""소비 변화 모니터링 — 일시적 변화와 구조적 변화를 구분한다 (소비 변화 모니터링 설계 5절)

이상 지출 후보 : 카테고리 지출이 직전 3개월 평균 대비 +20% 이상 AND 증가액이 월 소득의 1% 이상 (P-05)
구조적         : 후보 상태가 2개월 연속 지속, 또는 신규 정기결제·정기결제 금액 상승
일시적         : 후보가 1개월만 발생, 일회성 성격 카테고리, 또는 사용자가 "일회성"으로 지정한 달
확정 보류      : 비교할 이력이 부족하면(직전 3개월 + 최근 1개월 미만) 판정하지 않고 관찰
구조적 변화만 알림·재설계 대상이다. 일시적 변화는 낮음 등급(주간 요약)으로만 안내한다.
"""
from typing import Dict, List, Optional, Set, Tuple

from app.pipeline import params

BASE_MONTHS = 3


def _base(by_month: Dict[str, float], months: List[str], idx: int, one_off: Set[str]) -> Optional[float]:
    """months[idx] 직전 3개월의 평균 (일회성으로 지정된 달은 제외). 이력이 3개월 미만이면 None."""
    prev = months[max(idx - BASE_MONTHS, 0):idx]
    if len(prev) < BASE_MONTHS:
        return None
    vals = [by_month.get(m, 0.0) for m in prev if m not in one_off]
    return sum(vals) / len(vals) if vals else None


def detect(
    category_monthly: Dict[str, Dict[str, float]],
    window: List[str],
    monthly_income: Optional[float],
    fixed_by_merchant: Dict[str, Dict[str, float]],
    income_by_month: Dict[str, float],
    one_off: Set[Tuple[str, str]],
) -> dict:
    """반환: {"status": "ok"|"insufficient_history", "events": [...]}"""
    if len(window) < BASE_MONTHS + 1:
        return {"status": "insufficient_history", "events": [],
                "note": f"비교 이력이 부족합니다(최소 {BASE_MONTHS + 1}개월 필요). 관찰 중입니다."}

    last = len(window) - 1
    month = window[last]
    income = monthly_income or 0
    events: List[dict] = []

    for cat, by_month in category_monthly.items():
        if cat == "미분류":                      # 분류 확정 전 지출은 변화 판정에서 제외
            continue
        offs = {m for (c, m) in one_off if c == cat}
        base = _base(by_month, window, last, offs)
        if base is None or base <= 0:
            continue
        recent = by_month.get(month, 0.0)

        def is_cand(idx: int) -> bool:
            b = _base(by_month, window, idx, offs)
            cur = by_month.get(window[idx], 0.0)
            return (b is not None and b > 0 and window[idx] not in offs
                    and cur >= b * (1 + params.OUTLIER_GROWTH)
                    and (cur - b) >= income * params.OUTLIER_MIN_INCOME_SHARE)

        if month in offs:                       # 사용자가 일회성으로 지정한 달
            continue
        if is_cand(last):
            prev_cand = last >= 1 and is_cand(last - 1)
            if prev_cand:
                judgement, reason = "structural", "2개월 연속 평균을 넘었습니다"
            elif cat in params.G_ONE_OFF_CATEGORIES:
                judgement, reason = "temporary", "일회성 성격의 카테고리입니다"
            else:
                judgement, reason = "temporary", "이번 달에만 평균을 넘었습니다(다음 달 추이를 관찰)"
            excess = recent - base
            events.append(_event(
                "category_increase", cat, month, judgement, recent, base, excess, reason,
                f"{cat} 지출이 직전 3개월 평균보다 {excess / base * 100:.0f}% 늘었어요 "
                f"({base:,.0f}원 → {recent:,.0f}원)."))
        elif recent <= base * (1 - params.G_DECREASE_RATIO) and (base - recent) >= income * params.OUTLIER_MIN_INCOME_SHARE:
            events.append(_event(
                "category_decrease", cat, month, "temporary", recent, base, -(base - recent),
                "평균보다 줄었습니다",
                f"{cat} 지출이 직전 3개월 평균보다 {(base - recent) / base * 100:.0f}% 줄었어요 "
                f"({base:,.0f}원 → {recent:,.0f}원)."))

    # 고정지출: 신규 정기결제 / 금액 상승
    for merchant, by_month in fixed_by_merchant.items():
        months_present = [m for m in window if by_month.get(m, 0) > 0]
        if not months_present:
            continue
        first = window.index(months_present[0])
        if first >= last - 1 and first >= 1 and len(months_present) >= 1 and merchant_new_enough(window, first):
            amt = by_month[months_present[-1]]
            events.append(_event(
                "new_subscription", merchant, window[first], "structural", amt, 0.0, amt,
                "새 정기결제가 시작되었습니다",
                f"새 정기결제 '{merchant}'가 시작되었어요(월 {amt:,.0f}원)."))
            continue
        prior = [by_month[m] for m in window[:last] if by_month.get(m, 0) > 0]
        cur = by_month.get(month, 0.0)
        if prior and cur > 0:
            ref = sum(prior) / len(prior)
            if cur >= ref * (1 + params.G_FIXED_INCREASE_RATIO):
                events.append(_event(
                    "fixed_increase", merchant, month, "structural", cur, ref, cur - ref,
                    "정기결제 금액이 올랐습니다",
                    f"'{merchant}' 정기결제가 {ref:,.0f}원에서 {cur:,.0f}원으로 올랐어요."))

    # 수입 변화 (정기수입 월 합계)
    inc_prev = [income_by_month.get(m, 0.0) for m in window[max(last - BASE_MONTHS, 0):last]]
    inc_cur = income_by_month.get(month, 0.0)
    if inc_prev and sum(inc_prev) > 0:
        ref = sum(inc_prev) / len(inc_prev)
        change = (inc_cur - ref) / ref
        if abs(change) >= params.G_INCOME_CHANGE_RATIO:
            prev_month_change = (income_by_month.get(window[last - 1], 0.0) - ref) / ref if last >= 1 else 0
            judgement = "structural" if abs(prev_month_change) >= params.G_INCOME_CHANGE_RATIO else "temporary"
            events.append(_event(
                "income_change", "수입", month, judgement, inc_cur, ref, inc_cur - ref,
                "수입이 평균과 다릅니다",
                f"월 수입이 직전 평균 {ref:,.0f}원에서 {inc_cur:,.0f}원으로 {'늘었' if change > 0 else '줄었'}어요."))

    for e in events:
        e["grade"] = _grade(e)
    return {"status": "ok", "events": events, "month": month}


def merchant_new_enough(window: List[str], first_idx: int) -> bool:
    """관측 초반부터 있었던 정기결제를 '신규'로 오판하지 않도록, 최근 2개월 안에 처음 나타난 경우만 신규로 본다"""
    return first_idx >= len(window) - 2


def _event(etype: str, key: str, month: str, judgement: str, recent: float, baseline: float,
           monthly_impact: float, reason: str, message: str) -> dict:
    return {
        "event_type": etype, "category": key, "month": month, "judgement": judgement,
        "recent": round(recent), "baseline": round(baseline), "monthly_impact": round(monthly_impact),
        "growth_pct": round((recent / baseline - 1) * 100, 1) if baseline else None,
        "reason": reason, "message": message,
    }


def _grade(e: dict) -> str:
    """구조적 변화는 중간 이상, 일시적 변화·개선 소식은 낮음 (알림 설계 6절)"""
    if e["judgement"] == "structural" and e["monthly_impact"] > 0:
        return "medium"
    return "low"
