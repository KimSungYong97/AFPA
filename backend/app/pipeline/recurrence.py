"""주기성(반복) 감지 — 수입·고정지출 판별의 1차 기준

- 기준일 ±3일 (P-01/P-02): 주말·연휴로 입금/출금이 앞뒤로 밀리는 경우를 흡수한다.
  (금→월 이연 최대 3일. 공휴일 달력은 사용하지 않고 허용 편차로 흡수한다.)
- 금액 유사성 ±10% (P-03), 공과금·통신 ±30%
- 서로 다른 달에 최소 3회 (P-04)
"""
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Dict, Iterable, List, Optional

from app.pipeline import params


@dataclass
class Occurrence:
    key: str
    day: date
    amount: float


@dataclass
class Recurrence:
    key: str
    period_day: int          # 기준일(일자 중앙값)
    median_amount: float
    count: int
    months: int


def _day_gap(a: int, b: int) -> int:
    """월 경계(말일↔1일)를 고려한 일자 차이 (30일 기준 환형)"""
    d = abs(a - b)
    return min(d, 30 - d)


def detect_recurring(
    occurrences: Iterable[Occurrence],
    amount_tol: float = params.AMOUNT_TOL_FIXED,
    min_occurrences: int = params.MIN_OCCURRENCES,
) -> Dict[str, Recurrence]:
    """키별로 주기성 여부를 판정해 반복 패턴을 반환한다(미충족 키는 제외)."""
    groups: Dict[str, List[Occurrence]] = {}
    for o in occurrences:
        groups.setdefault(o.key, []).append(o)

    result: Dict[str, Recurrence] = {}
    for key, items in groups.items():
        rec = _evaluate(key, items, amount_tol, min_occurrences)
        if rec is not None:
            result[key] = rec
    return result


def _evaluate(key: str, items: List[Occurrence], amount_tol: float,
              min_occurrences: int) -> Optional[Recurrence]:
    if len(items) < min_occurrences:
        return None
    days = [it.day.day for it in items]
    amounts = [it.amount for it in items]
    ref_day = int(round(median(days)))
    ref_amt = median(amounts)
    if ref_amt <= 0:
        return None

    conforming = [
        it for it in items
        if _day_gap(it.day.day, ref_day) <= params.RECUR_DAY_TOLERANCE
        and abs(it.amount - ref_amt) <= ref_amt * amount_tol
    ]
    months = {(it.day.year, it.day.month) for it in conforming}
    if len(months) < min_occurrences:
        return None
    if len(conforming) / len(items) < params.RECUR_CONFORM_RATIO:
        return None
    return Recurrence(key=key, period_day=ref_day, median_amount=float(ref_amt),
                      count=len(conforming), months=len(months))
