"""월중 현금 전망 엔진: 소비 속도 · 예정 일정 · 월중 최저 현금 · 위험도"""
from datetime import date

from app.pipeline.types import Flow
from app.planner.forecast import forecast


def _flows(this_month_shopping=0.0, months=(5, 6, 7)):
    out = []
    for m in months:                                            # 완결된 달: 매달 쇼핑 50만 + 월세 60만(25일) + 월급 300만(25일)
        out.append(Flow(date(2026, m, 10), 500_000, "out", "card", "쇼핑몰", "variable", "쇼핑"))
        out.append(Flow(date(2026, m, 25), 600_000, "out", "bank", "월세", "fixed", "주거", recurring=True))
        out.append(Flow(date(2026, m, 25), 3_000_000, "in", "bank", "월급", "income", "근로수입", recurring=True))
    if this_month_shopping:
        out.append(Flow(date(2026, 8, 5), this_month_shopping, "out", "card", "쇼핑몰", "variable", "쇼핑"))
    return out


AS_OF = date(2026, 8, 10)


def test_normal_month_is_ok():
    f = forecast(AS_OF, _flows(150_000), liquid_cash=2_000_000, monthly_income=3_000_000)
    assert f["status"] == "ok" and f["risk"] == "ok"
    assert f["days_elapsed"] == 10 and f["days_in_month"] == 31
    names = [(e["name"], e["kind"]) for e in f["upcoming"]]
    assert ("월세", "고정지출") in names and ("월급", "수입") in names     # 아직 안 나간·안 들어온 정기 일정
    assert f["end_cash"] > f["cash_now"] - 1                            # 월급이 들어오고 평소 속도면 잔액이 늘어난다


def test_overspending_triggers_watch_with_category():
    f = forecast(AS_OF, _flows(1_200_000), liquid_cash=3_000_000, monthly_income=3_000_000)
    assert f["risk"] == "watch" and f["overspend"] > 0
    assert f["overspent_categories"][0]["category"] == "쇼핑"
    assert f["projected_variable"] >= f["spent_so_far"]                 # 예상은 이미 쓴 금액보다 작을 수 없다


def test_cash_running_out_is_danger_with_date():
    f = forecast(AS_OF, _flows(1_200_000), liquid_cash=150_000, monthly_income=3_000_000)
    assert f["risk"] == "danger" and f["min_cash"] < 0
    assert date.fromisoformat(f["min_cash_date"]) > AS_OF               # 월급일 전에 바닥


def test_paid_items_are_not_counted_again():
    flows = _flows(100_000) + [Flow(date(2026, 8, 3), 600_000, "out", "bank", "월세", "fixed", "주거", recurring=True)]
    f = forecast(AS_OF, flows, 2_000_000, 3_000_000)
    assert ("월세", "고정지출") not in [(e["name"], e["kind"]) for e in f["upcoming"]]


def test_not_enough_history_or_month_end():
    only_current = [Flow(date(2026, 8, 2), 10_000, "out", "card", "x", "variable", "식비")]
    assert forecast(AS_OF, only_current, 1_000_000)["status"] == "insufficient_history"
    assert forecast(date(2026, 8, 31), _flows(), 1_000_000)["status"] == "month_end"
