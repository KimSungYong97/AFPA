"""주기성 감지 (P-01~P-04)"""
from datetime import date

from app.pipeline.recurrence import Occurrence, detect_recurring


def occ(key, y, m, d, amt):
    return Occurrence(key, date(y, m, d), amt)


def test_monthly_same_day_is_recurring():
    items = [occ("넷플릭스", 2026, m, 10, 17000) for m in (3, 4, 5, 6)]
    rec = detect_recurring(items)
    assert "넷플릭스" in rec and rec["넷플릭스"].period_day == 10


def test_weekend_shift_within_three_days_is_tolerated():
    # 25일 급여가 주말이면 22~23일로 당겨진다 (P-01: ±3일)
    items = [occ("급여", 2026, 3, 25, 3_200_000), occ("급여", 2026, 4, 24, 3_200_000),
             occ("급여", 2026, 5, 22, 3_200_000), occ("급여", 2026, 6, 25, 3_200_000)]
    assert "급여" in detect_recurring(items)


def test_day_drift_beyond_tolerance_is_not_recurring():
    items = [occ("A", 2026, 3, 5, 10000), occ("A", 2026, 4, 20, 10000), occ("A", 2026, 5, 12, 10000)]
    assert detect_recurring(items) == {}


def test_two_occurrences_are_not_enough():                      # P-04: 최소 3회
    items = [occ("A", 2026, 3, 10, 10000), occ("A", 2026, 4, 10, 10000)]
    assert detect_recurring(items) == {}


def test_same_month_repeats_do_not_count_as_months():
    items = [occ("A", 2026, 3, 10, 10000), occ("A", 2026, 3, 11, 10000), occ("A", 2026, 3, 12, 10000)]
    assert detect_recurring(items) == {}                         # 서로 다른 달 3개 필요


def test_amount_tolerance_fixed_vs_utility():
    items = [occ("전기", 2026, 3, 26, 40000), occ("전기", 2026, 4, 26, 48000),
             occ("전기", 2026, 5, 26, 52000), occ("전기", 2026, 6, 26, 44000)]
    assert detect_recurring(items, amount_tol=0.10) == {}        # 일반 고정지출 ±10%에는 미달
    assert "전기" in detect_recurring(items, amount_tol=0.30)    # 공과금·통신 ±30%


def test_month_end_wrap():
    items = [occ("A", 2026, 3, 30, 10000), occ("A", 2026, 4, 30, 10000), occ("A", 2026, 5, 29, 10000),
             occ("A", 2026, 6, 30, 10000)]
    assert "A" in detect_recurring(items)
