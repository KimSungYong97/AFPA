"""행동 후보 순위 엔진 + 소비 변화 모니터링 판정"""
from datetime import date

import pytest

from app.planner import candidates as ce
from app.planner import monitoring as mon
from app.planner.path import PathGoal, PathInput

AS_OF = date(2026, 8, 7)
WINDOW = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]


def _ctx(budget=1_000_000, cats=None, subs=None, outliers=None, emergency=None, exclude=None, goals=None):
    goals = goals if goals is not None else [PathGoal("전세", 30_000_000, 0, date(2028, 8, 7), 1)]
    return ce.CandidateContext(
        path_input=PathInput(AS_OF, budget, goals, annual_return=0.0), monthly_income=3_000_000,
        category_monthly=cats or {}, window=WINDOW, subscriptions=subs or [], outliers=outliers or [],
        emergency=emergency or {"coverage_ratio": 150, "required": 3_000_000, "liquid_cash": 4_500_000,
                                "monthly_essential_expense": 1_000_000},
        exclude_keys=exclude or set())


def _even(amount):
    return {m: amount for m in WINDOW}


# ---------------------------------------------------------------- 후보 순위
def test_candidates_are_ranked_by_months_saved_with_individual_effects():
    ctx = _ctx(cats={"쇼핑": _even(600_000), "문화/여가": _even(200_000)},
               subs=[{"merchant": "넷플릭스", "monthly_amount": 17_000}])
    cands = ce.generate(ctx)
    keys = [c["key"] for c in cands]
    assert keys[:3] == ["cut:쇼핑", "cut:문화/여가", "sub:넷플릭스"]     # 절감액이 클수록 단축 효과가 큼
    assert [c["rank"] for c in cands] == [1, 2, 3]
    shop = cands[0]
    assert shop["monthly_saving"] == 90_000                             # 600,000 × 15%
    # 30M / 1,000,000 = 30개월 → 1,090,000이면 28개월 (단독 효과)
    assert shop["effect"]["months_saved"] == 30 - 28
    assert shop["effect"]["headline_goal"] == "전세"


def test_essential_categories_are_not_cut_but_outliers_can_be_restored():
    ctx = _ctx(cats={"식비": _even(500_000), "쇼핑": _even(300_000)},
               outliers=[{"category": "식비", "recent": 650_000, "baseline": 500_000, "growth_pct": 30.0}])
    keys = [c["key"] for c in ce.generate(ctx)]
    assert "cut:식비" not in keys and "restore:식비" in keys           # 필수 카테고리는 급증분만 되돌린다


def test_same_category_alternatives_conflict_and_combine_uses_larger_only():
    ctx = _ctx(cats={"쇼핑": {**_even(300_000), "2026-07": 450_000}},
               outliers=[{"category": "쇼핑", "recent": 450_000, "baseline": 300_000, "growth_pct": 50.0}])
    cands = ce.generate(ctx)
    by = {c["key"]: c for c in cands}
    assert by["cut:쇼핑"]["conflicts_with"] == ["restore:쇼핑"] and by["restore:쇼핑"]["conflicts_with"] == ["cut:쇼핑"]
    comb = ce.combine(ctx, cands, ["cut:쇼핑", "restore:쇼핑"])
    assert len(comb["selected"]) == 1 and len(comb["ignored_conflicts"]) == 1
    assert comb["total_monthly_saving"] == max(by["cut:쇼핑"]["monthly_saving"], by["restore:쇼핑"]["monthly_saving"])


def test_combined_effect_is_recomputed_not_summed():
    ctx = _ctx(cats={"쇼핑": _even(600_000), "문화/여가": _even(600_000), "기타": _even(600_000)},
               goals=[PathGoal("전세", 20_000_000)])
    cands = ce.generate(ctx)
    assert [c["effect"]["months_saved"] for c in cands] == [1, 1, 1]       # 20M: 1.0M→20개월, 1.09M→19개월
    comb = ce.combine(ctx, cands, [c["key"] for c in cands])
    assert comb["total_monthly_saving"] == 270_000                          # 90,000 × 3
    assert comb["combined_months_saved"] == 4                               # 1.27M → 16개월(15.7 올림)
    assert comb["sum_of_individual_months_saved"] == 3                      # 단독 효과를 더한 값(3)과 다르다 → 합산 금지


def test_emergency_fund_first_is_mandatory_and_delays_goal():
    ctx = _ctx(cats={"쇼핑": _even(600_000)},
               emergency={"coverage_ratio": 40.0, "required": 3_000_000, "liquid_cash": 1_200_000,
                          "monthly_essential_expense": 1_000_000})
    cands = ce.generate(ctx)
    first = cands[0]
    assert first["key"] == "emergency" and first["mandatory"] is True     # R-01: 비상금 우선, 순위와 무관
    assert first["params"]["monthly"] == 150_000                          # 부족분 1,800,000 / 12개월
    assert first["effect"]["months_saved"] < 0                            # 먼저 채우는 동안 목표는 늦어진다
    assert [c["key"] for c in cands[1:]] == ["cut:쇼핑"]


def test_deficit_first_when_budget_negative_and_effect_is_deficit_closed_pct():
    ctx = _ctx(budget=-200_000, cats={"쇼핑": _even(600_000)})
    cands = ce.generate(ctx)
    assert cands[0]["key"] == "deficit" and cands[0]["mandatory"]
    cut = next(c for c in cands if c["key"] == "cut:쇼핑")
    assert cut["effect"]["deficit_closed_pct"] == 45.0                    # 90,000 / 200,000
    assert cut["effect"]["makes_reachable"] is False                      # 아직 적자라 달성은 불가능


def test_candidate_that_turns_unreachable_goal_reachable_ranks_first():
    ctx = _ctx(budget=-50_000, cats={"쇼핑": _even(600_000), "기타": _even(100_000)},
               goals=[PathGoal("A", 1_000_000)])
    cands = [c for c in ce.generate(ctx) if not c["mandatory"]]
    assert cands[0]["key"] == "cut:쇼핑" and cands[0]["effect"]["makes_reachable"] is True


def test_unclassified_noise_and_adopted_items_are_excluded():
    ctx = _ctx(cats={"미분류": _even(900_000), "쇼핑": _even(600_000), "기타": _even(10_000)},
               exclude={"cut:쇼핑"})
    assert [c["key"] for c in ce.generate(ctx)] == []                      # 미분류·소액 노이즈·이미 수락한 항목 제외


def test_idle_cash_move_candidate_only_when_emergency_is_satisfied():
    ctx = _ctx(emergency={"coverage_ratio": 300, "required": 3_000_000, "liquid_cash": 12_000_000,
                          "monthly_essential_expense": 1_000_000})
    c = ce.generate(ctx)[0]
    assert c["key"] == "cash_move" and c["action_type"] == "자산 비중 조정"
    assert c["monthly_saving"] == round(8_000_000 * (0.03 - 0.001) / 12, -2)


def test_no_goal_ranks_by_saving_amount():
    ctx = _ctx(goals=[], cats={"쇼핑": _even(600_000), "기타": _even(200_000)})
    cands = ce.generate(ctx)
    assert [c["key"] for c in cands] == ["cut:쇼핑", "cut:기타"] and cands[0]["effect"]["months_saved"] is None


# ---------------------------------------------------------------- 소비 변화 판정
def _by(values):
    return dict(zip(WINDOW, values))


def test_one_month_spike_is_temporary():
    res = mon.detect({"식비": _by([400_000, 400_000, 400_000, 400_000, 600_000])}, WINDOW, 3_000_000, {}, {}, set())
    ev = res["events"][0]
    assert (ev["judgement"], ev["grade"]) == ("temporary", "low")
    assert ev["growth_pct"] == 50.0


def test_two_consecutive_months_is_structural_medium():
    res = mon.detect({"식비": _by([400_000, 400_000, 400_000, 500_000, 600_000])}, WINDOW, 3_000_000, {}, {}, set())
    ev = res["events"][0]
    assert (ev["judgement"], ev["grade"]) == ("structural", "medium")
    assert "2개월 연속" in ev["reason"]


def test_one_off_like_category_and_user_marks_are_temporary_or_skipped():
    only_spike = [400_000, 400_000, 400_000, 400_000, 900_000]
    res = mon.detect({"의료/건강": _by(only_spike)}, WINDOW, 3_000_000, {}, {}, set())
    assert res["events"][0]["judgement"] == "temporary"                  # 일회성 성격 카테고리
    res = mon.detect({"쇼핑": _by(only_spike)}, WINDOW, 3_000_000, {}, {}, {("쇼핑", "2026-07")})
    assert res["events"] == []                                            # 사용자가 '일회성'으로 지정한 달


def test_small_increase_below_income_share_is_noise():
    res = mon.detect({"기타": _by([10_000, 10_000, 10_000, 10_000, 20_000])}, WINDOW, 3_000_000, {}, {}, set())
    assert res["events"] == []                                            # +100%이지만 증가액 10,000원 < 월 소득 1%


def test_insufficient_history_is_observation_only():
    res = mon.detect({"식비": {"2026-06": 1, "2026-07": 100}}, ["2026-06", "2026-07"], 100_000, {}, {}, set())
    assert res["status"] == "insufficient_history" and res["events"] == []


def test_new_subscription_and_fixed_price_increase_are_structural():
    fixed = {"새구독": {"2026-07": 15_000},
             "넷플릭스": {m: 17_000 for m in WINDOW[:-1]} | {"2026-07": 20_000}}
    res = mon.detect({}, WINDOW, 3_000_000, fixed, {}, set())
    kinds = {e["event_type"]: e for e in res["events"]}
    assert kinds["new_subscription"]["judgement"] == "structural"
    assert kinds["fixed_increase"]["monthly_impact"] == 3_000
    assert all(e["grade"] == "medium" for e in res["events"])


def test_income_change_needs_two_months_to_be_structural():
    inc = _by([3_000_000, 3_000_000, 3_000_000, 3_000_000, 2_400_000])
    ev = mon.detect({}, WINDOW, 3_000_000, {}, inc, set())["events"][0]
    assert ev["event_type"] == "income_change" and ev["judgement"] == "temporary"
    inc2 = _by([3_000_000, 3_000_000, 3_000_000, 2_400_000, 2_400_000])
    assert mon.detect({}, WINDOW, 3_000_000, {}, inc2, set())["events"][0]["judgement"] == "structural"


def test_decrease_is_reported_as_low_good_news():
    res = mon.detect({"쇼핑": _by([500_000, 500_000, 500_000, 500_000, 300_000])}, WINDOW, 3_000_000, {}, {}, set())
    ev = res["events"][0]
    assert ev["event_type"] == "category_decrease" and ev["grade"] == "low"
