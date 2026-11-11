"""자산 성장 경로 엔진 + 시나리오 엔진 — 손으로 계산한 골든 케이스와 단조성 검증"""
import math
from datetime import date

import pytest

from app.planner.path import PathGoal, PathInput, compare, simulate
from app.planner.scenarios import Scenario, ScenarioError, apply, run_scenarios

AS_OF = date(2026, 8, 7)


def _inp(budget, goals, ret=0.0, **kw):
    return PathInput(as_of=AS_OF, monthly_budget=budget, goals=goals, annual_return=ret, **kw)


def test_waterfall_golden_case_without_return():
    r = simulate(_inp(1_000_000, [PathGoal("A", 12_000_000, 0, date(2027, 8, 7), 1),
                                  PathGoal("B", 6_000_000, 0, None, 2)]))
    a, b = r.goal("A"), r.goal("B")
    assert (a.completion_k, a.status, a.required_monthly) == (12, "on_track", 1_000_000)
    assert (b.completion_k, b.status) == (18, "no_deadline")       # A가 끝난 뒤 그 몫이 B로 이어진다
    assert r.series[-1]["net_worth"] == 18_000_000                  # 목표 적립금 + 자유 저축 = 총 납입액


def test_compound_return_matches_annuity_formula():
    ret = 0.12
    r_m = (1 + ret) ** (1 / 12) - 1
    n = math.ceil(math.log(1 + 24_000_000 * r_m / 1_000_000) / math.log(1 + r_m))
    res = simulate(_inp(1_000_000, [PathGoal("A", 24_000_000)], ret))
    assert res.goal("A").completion_k == n and n < 24                # 수익률만큼 빨라진다 (월 납입 후 월복리 = 보통연금 공식)


def test_late_goal_reports_gap_and_shortfall_at_deadline():
    res = simulate(_inp(1_000_000, [PathGoal("A", 24_000_000, 0, date(2027, 8, 7), 1)]))
    a = res.goal("A")
    assert a.status == "late" and a.completion_k == 24 and a.gap_months == 12
    assert a.balance_at_deadline == 12_000_000 and a.shortfall_at_deadline == 12_000_000


def test_priority_order_starves_lower_priority_when_budget_is_short():
    res = simulate(_inp(1_000_000, [PathGoal("낮음", 6_000_000, 0, date(2027, 2, 7), 2),
                                    PathGoal("높음", 12_000_000, 0, date(2027, 8, 7), 1)]))
    assert res.goal("높음").first_month_alloc == 1_000_000 and res.goal("낮음").first_month_alloc == 0
    assert res.goal("높음").completion_k == 12 and res.goal("낮음").completion_k == 18


def test_negative_budget_withdraws_from_lowest_priority_and_never_completes():
    res = simulate(_inp(-100_000, [PathGoal("A", 5_000_000, 1_000_000, None, 1)]), series_months=12)
    assert res.goal("A").status == "unreachable"
    assert res.series[12]["balances"]["A"] == 0                       # 1,000,000 − 100,000×10 이후 0 (음수 불가)


def test_completed_goal_is_done_at_zero():
    res = simulate(_inp(500_000, [PathGoal("A", 1_000_000, 1_000_000)]))
    assert res.goal("A").status == "done" and res.goal("A").completion_k == 0


def test_more_budget_never_delays_any_goal():
    goals = [PathGoal("A", 30_000_000, 2_000_000, date(2029, 8, 7), 1), PathGoal("B", 10_000_000, 0, None, 2)]
    prev = None
    for budget in range(300_000, 3_000_001, 300_000):
        res = simulate(_inp(budget, goals, 0.02))
        ks = [g.completion_k for g in res.goals]
        if prev:
            assert all(k <= p for k, p in zip(ks, prev))              # 단조성: 역전·불연속 없음
        prev = ks


def test_one_off_expense_delays_goal():
    base = _inp(1_000_000, [PathGoal("A", 12_000_000)])
    delayed = simulate(apply(Scenario("expense", month=3, amount=3_000_000), base))
    assert delayed.goal("A").completion_k == 15 and simulate(base).goal("A").completion_k == 12


# ---------------------------------------------------------------- 시나리오
def test_scenarios_compare_against_base():
    base_in = _inp(1_000_000, [PathGoal("A", 24_000_000, 0, date(2028, 8, 7), 1)], 0.02)
    base = simulate(base_in)
    out = run_scenarios(base_in, base, [
        Scenario("save_delta", delta=200_000),
        Scenario("goal", goal="A", shift_months=12),
        Scenario("return", case="optimistic"),
    ], monthly_income=3_000_000)
    assert len(out) == 3
    saved = out[0]["goals"][0]["months_saved"]
    assert saved is not None and saved > 0                            # 저축을 늘리면 앞당겨진다
    assert out[1]["paths"].goal("A").gap_months < base.goal("A").gap_months   # 기한을 미루면 지연폭이 줄어든다
    assert out[2]["goals"][0]["months_saved"] >= 0                    # 낙관 수익률은 늦추지 않는다
    assert out[0]["net_worth_diff"] > 0


def test_return_cases_are_monotonic():
    base_in = _inp(800_000, [PathGoal("A", 40_000_000)])
    ks = []
    for case in ("conservative", "base", "optimistic"):
        res = simulate(apply(Scenario("return", case=case), base_in))
        ks.append(res.goal("A").completion_k)
    assert ks[0] >= ks[1] >= ks[2]


@pytest.mark.parametrize("sc", [
    Scenario("expense", month=0, amount=1000),
    Scenario("expense", month=3, amount=-5),
    Scenario("expense", month=3, amount=2_000_000_000),
    Scenario("save_delta", delta=900_000_000),
    Scenario("goal", goal="없는 목표", shift_months=3),
    Scenario("goal", goal="A", shift_months=999),
    Scenario("return", case="미친낙관"),
    Scenario("unknown"),
])
def test_scenario_input_validation(sc):
    base_in = _inp(1_000_000, [PathGoal("A", 10_000_000, 0, date(2028, 8, 7), 1)])
    with pytest.raises(ScenarioError):
        run_scenarios(base_in, simulate(base_in), [sc], monthly_income=3_000_000)


def test_at_most_three_scenarios():
    base_in = _inp(1_000_000, [PathGoal("A", 10_000_000)])
    with pytest.raises(ScenarioError):
        run_scenarios(base_in, simulate(base_in), [Scenario("save_delta", delta=1000)] * 4)


def test_compare_marks_unreachable_to_reachable():
    broke = _inp(-50_000, [PathGoal("A", 1_000_000)])
    fixed = _inp(100_000, [PathGoal("A", 1_000_000)])
    row = compare(simulate(broke), simulate(fixed))[0]
    assert row["makes_reachable"] is True and row["months_saved"] is None
