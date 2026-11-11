"""후보 공급자·규칙 판정기 등록 인터페이스 + 목표별 수익률 — 3차 이후 모듈이 꽂히는 자리의 계약 검증"""
from datetime import date

import pytest

from app.planner import candidates as ce
from app.planner import registry
from app.planner.path import PathGoal, PathInput, apply_change, merge_changes, simulate
from app.planner.registry import Eligibility

AS_OF = date(2026, 8, 7)
WINDOW = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]


def _ctx(facts=None, annual_return=0.0):
    goals = [PathGoal("전세", 30_000_000, 6_000_000, date(2028, 8, 7), 1)]
    return ce.CandidateContext(
        path_input=PathInput(AS_OF, 1_000_000, goals, annual_return=annual_return), monthly_income=3_000_000,
        category_monthly={"쇼핑": {m: 600_000 for m in WINDOW}}, window=WINDOW,
        emergency={"coverage_ratio": 150, "required": 3_000_000, "liquid_cash": 4_500_000, "monthly_essential_expense": 1_000_000},
        facts=facts or {"age": 29, "monthly_income": 3_000_000})


class FakeDepositProvider:
    """3차 예·적금 모듈의 모양: 전세 자금을 연 4% 적금(세후)으로 옮기는 후보"""
    name = "fake_deposit"

    def generate(self, ctx):
        return [ce.make_candidate(
            "deposit:A적금", "예·적금", "A은행 적금으로 옮기기", "금리 4.0% 적금", 0.0,
            {"kind": "deposit", "product": "A적금"}, {"금리": "4.0%"}, "deposit:전세", provider=self.name,
            change={"goal_returns": {"전세": {"annual_return": 0.04, "tax_rate": 0.154}}})]


class YouthOnlyRule:
    """3차 규칙 엔진의 모양: 만 34세 이하만 가입할 수 있는 상품"""
    def check(self, cand, facts):
        if cand["key"].startswith("deposit:") and (facts.get("age") or 0) > 34:
            return Eligibility(False, "R-DEP-01", "만 34세 이하만 가입할 수 있어요")
        return Eligibility(True)


@pytest.fixture(autouse=True)
def clean_registry():
    yield
    registry.unregister_provider("fake_deposit")
    registry.clear_rule_checkers()


def test_provider_candidates_are_ranked_with_builtin_ones():
    registry.register_provider(FakeDepositProvider())
    cands = ce.generate(_ctx(annual_return=0.0))
    by_key = {c["key"]: c for c in cands}
    assert "deposit:A적금" in by_key and "cut:쇼핑" in by_key                  # 공급자가 달라도 한 순위표에 오른다
    dep = by_key["deposit:A적금"]
    assert dep["provider"] == "fake_deposit" and dep["effect"]["months_saved"] > 0   # 수익률이 오르면 목표가 빨라진다
    assert [c["rank"] for c in cands if "rank" in c] == list(range(1, len([c for c in cands if "rank" in c]) + 1))


def test_rule_checker_excludes_ineligible_candidates_with_reason():
    registry.register_provider(FakeDepositProvider())
    registry.register_rule_checker(YouthOnlyRule())
    rep = ce.generate_report(_ctx(facts={"age": 40}))
    assert "deposit:A적금" not in [c["key"] for c in rep["candidates"]]
    assert rep["excluded"] == [{"key": "deposit:A적금", "title": "A은행 적금으로 옮기기",
                                "rule_id": "R-DEP-01", "reason": "만 34세 이하만 가입할 수 있어요"}]
    ok = ce.generate_report(_ctx(facts={"age": 29}))
    assert "deposit:A적금" in [c["key"] for c in ok["candidates"]] and ok["excluded"] == []


def test_combine_merges_changes_of_different_providers():
    registry.register_provider(FakeDepositProvider())
    ctx = _ctx()
    cands = ce.generate(ctx)
    combo = ce.combine(ctx, cands, ["deposit:A적금", "cut:쇼핑"])
    single = {c["key"]: c["effect"]["months_saved"] for c in cands}
    assert combo["combined_months_saved"] >= max(single["deposit:A적금"], single["cut:쇼핑"])
    assert set(combo["selected"]) == {"deposit:A적금", "cut:쇼핑"}


def test_duplicate_provider_name_is_rejected():
    registry.register_provider(FakeDepositProvider())
    with pytest.raises(ValueError):
        registry.register_provider(FakeDepositProvider())


# ---------------------------------------------------------------- 목표별 수익률
def _path(goal_return=None, tax=0.0, base_return=0.03):
    g = [PathGoal("A", 12_000_000, 0, None, 1, annual_return=goal_return, tax_rate=tax),
         PathGoal("B", 12_000_000, 0, None, 2)]
    return simulate(PathInput(AS_OF, 500_000, g, annual_return=base_return))


def test_goal_specific_return_changes_only_that_goal():
    base, higher = _path(), _path(goal_return=0.10)
    assert higher.goal("A").completion_k < base.goal("A").completion_k
    # B는 A가 끝난 뒤 그 몫을 이어받으므로 A가 빨리 끝나면 B도 빨라질 수는 있어도 늦어지지는 않는다
    assert higher.goal("B").completion_k <= base.goal("B").completion_k


def test_tax_reduces_effective_return_and_default_is_unchanged():
    gross, taxed = _path(goal_return=0.05), _path(goal_return=0.05, tax=0.154)
    assert taxed.goal("A").completion_k >= gross.goal("A").completion_k
    assert _path(goal_return=0.03).goal("A").completion_k == _path().goal("A").completion_k   # 값이 같으면 기본과 동일


def test_apply_change_is_pure_and_merge_changes_sums():
    inp = PathInput(AS_OF, 1_000_000, [PathGoal("A", 10_000_000)], annual_return=0.03)
    out = apply_change(inp, {"monthly_delta": 200_000, "one_offs": {2: 50_000}, "goal_returns": {"A": {"annual_return": 0.05}}})
    assert inp.monthly_budget == 1_000_000 and inp.goals[0].annual_return is None          # 원본은 바뀌지 않는다
    assert out.monthly_budget == 1_200_000 and out.one_offs == {2: 50_000} and out.goals[0].annual_return == 0.05
    merged = merge_changes([{"monthly_delta": 1, "one_offs": {1: 5}}, {"monthly_delta": 2, "one_offs": {1: 5, 2: 1}}])
    assert merged["monthly_delta"] == 3 and merged["one_offs"] == {1: 10.0, 2: 1.0}
