"""6개 엔진 — 손으로 계산한 골든 케이스 (결정적 계산, 오차 0)"""
from datetime import date

import pytest

from app.pipeline.engines import EngineInput, compute, observation_window
from app.pipeline.types import Flow, GoalInfo, Holding, OnboardingInfo

AS_OF = date(2026, 8, 7)
MONTHS = [3, 4, 5, 6, 7]


def _flows(income=3_000_000, fixed=1_000_000, essential_var=600_000, other_var=300_000,
           saving=600_000, loan=0, months=MONTHS):
    out = []
    for m in months:
        d = date(2026, m, 25)
        if income:
            out.append(Flow(d, income, "in", "bank", "급여", "income", "근로수입", recurring=True))
        out.append(Flow(d, fixed, "out", "bank", "월세", "fixed", "주거", recurring=True))
        out.append(Flow(d, essential_var, "out", "card", "식당", "variable", "식비"))
        out.append(Flow(d, other_var, "out", "card", "쇼핑몰", "variable", "쇼핑"))
        if saving:
            out.append(Flow(d, saving, "out", "bank", "적금", "saving", "저축·투자"))
        if loan:
            out.append(Flow(d, loan, "out", "loan", "대출 원리금", "fixed", "대출상환", recurring=True))
    return out


def _holdings(cash=3_000_000, debt=0):
    h = [Holding("asset", "cash", "입출금", "입출금", cash, emergency_eligible=True),
         Holding("asset", "cash", "페이머니", "페이", 500_000, emergency_eligible=False),
         Holding("asset", "invest", "주식/ETF", "ETF", 1_500_000)]
    if debt:
        h.append(Holding("liability", "secured", "전세자금대출", "대출", debt))
    return h


def test_observation_window_uses_complete_months_only():
    window, partial = observation_window(AS_OF, _flows(months=[3, 4, 5, 6, 7, 8]))
    assert window == [(2026, m) for m in (3, 4, 5, 6, 7)] and partial is False   # 진행 중인 8월 제외


def test_golden_case_cash_flow_balance_and_health():
    r = compute(EngineInput(AS_OF, _flows(), _holdings()))
    cf = r.details["cash_flow"]
    assert (cf["monthly_income"], cf["fixed_expense"], cf["variable_expense"]) == (3_000_000, 1_000_000, 900_000)
    assert cf["monthly_disposable"] == 2_000_000
    assert r.net_cash_flow == 1_100_000                       # 월 여유 자금 = 수입 − (고정 + 평균 변동)
    assert r.net_worth == 5_000_000
    assert r.savings_ratio == 20.0                             # 600k / 3,000k (D-01: 당월 납입액 기준)
    assert r.consumption_ratio == pytest.approx(63.33, abs=0.01)
    # 필수 월 지출 = 고정 1,000k + 필수 변동(식비) 600k = 1,600k, ×3개월 = 4,800k, 현금성 3,000k
    em = r.details["emergency_fund"]
    assert (em["required"], em["liquid_cash"]) == (4_800_000, 3_000_000)
    assert r.emergency_fund_ratio == 62.5                      # 페이머니는 제외 (D-06)
    # 건강도 = 저축 (0.2/0.3)*30 + 부채 30 + 비상금 0.625*20 + 소비통제 20
    assert r.health_score == pytest.approx(20 + 30 + 12.5 + 20, abs=0.05)
    assert r.dsr_ratio == 0.0


def test_freelancer_needs_six_months_of_emergency_fund():
    onboarding = OnboardingInfo(employment_status="FREELANCER")
    r = compute(EngineInput(AS_OF, _flows(), _holdings(), onboarding))
    assert r.details["emergency_fund"]["months"] == 6          # P-06
    assert r.emergency_fund_ratio == 31.25


def test_dsr_and_debt_ratio_use_loan_service_and_assets():
    r = compute(EngineInput(AS_OF, _flows(loan=400_000), _holdings(cash=3_000_000, debt=2_000_000)))
    assert r.dsr_ratio == pytest.approx(13.33, abs=0.01)       # 400k / 3,000k, DTI가 아닌 DSR
    assert r.debt_ratio == pytest.approx(2_000_000 / 5_000_000 * 100)
    # 월 여유 자금에는 대출 원리금(금융 고정지출)이 반영된다
    assert r.net_cash_flow == 1_100_000 - 400_000


def test_dsr_penalty_curve():
    low = compute(EngineInput(AS_OF, _flows(loan=300_000), _holdings()))     # DSR 10% → 감점 없음
    high = compute(EngineInput(AS_OF, _flows(loan=1_350_000), _holdings()))  # DSR 45% → 30~60% 구간 선형 감소
    assert low.details["health"]["components"]["debt"]["points"] == 30
    assert high.details["health"]["components"]["debt"]["points"] == pytest.approx(15.0, abs=0.1)


def test_missing_income_keeps_ratios_null_not_zero():
    r = compute(EngineInput(AS_OF, _flows(income=0), _holdings()))
    assert r.monthly_income_net is None
    assert r.health_score is None and r.potential_score is None
    assert r.savings_ratio is None and r.consumption_ratio is None and r.dsr_ratio is None


def test_irregular_income_falls_back_to_recent_three_month_average():
    flows = [f for f in _flows(income=0)]
    for m, amt in zip((5, 6, 7), (2_000_000, 4_000_000, 3_000_000)):    # 정기성 없는 프리랜서 입금
        flows.append(Flow(date(2026, m, 10 + m), amt, "in", "bank", "프로젝트 대금", "income", "비정기수입"))
    r = compute(EngineInput(AS_OF, flows, _holdings()))
    assert r.monthly_income_net == 3_000_000
    assert any("최근 3개월 입금 평균" in q for q in r.details["data_quality"])


def test_outlier_requires_growth_and_income_share():
    flows = _flows()
    # 7월 쇼핑이 직전 3개월(월 300k) 대비 +100% → 이상 지출
    flows = [f for f in flows if not (f.category == "쇼핑" and f.occurred_on.month == 7)]
    flows.append(Flow(date(2026, 7, 25), 600_000, "out", "card", "쇼핑몰", "variable", "쇼핑"))
    r = compute(EngineInput(AS_OF, flows, _holdings()))
    assert [o["category"] for o in r.details["spending"]["outliers"]] == ["쇼핑"]
    assert r.details["spending"]["outliers"][0]["growth_pct"] == 100.0

    # 증가율은 크지만 증가액이 월 소득의 1% 미만이면 소액 노이즈로 제외 (P-05)
    small = [f for f in _flows() if not (f.category == "쇼핑" and f.occurred_on.month == 7)]
    small.append(Flow(date(2026, 7, 25), 310_000, "out", "card", "쇼핑몰", "variable", "쇼핑"))
    assert compute(EngineInput(AS_OF, small, _holdings())).details["spending"]["outliers"] == []


def test_potential_full_vs_basic_when_no_goal():
    goals = [GoalInfo("전세", 50_000_000, 14_000_000, date(2028, 12, 31), 1)]
    full = compute(EngineInput(AS_OF, _flows(), _holdings(), OnboardingInfo(birth_date=date(1998, 3, 14)), goals))
    basic = compute(EngineInput(AS_OF, _flows(), _holdings(), OnboardingInfo(birth_date=date(1998, 3, 14))))
    assert full.details["potential"]["kind"] == "full" and basic.details["potential"]["kind"] == "basic"
    assert "velocity" not in basic.details["potential"]["components"]   # 목표가 없으면 진척 속도 축 제외
    # 필요 월 저축액 = 36M / 28개월 ≈ 1.286M, 월 여유 자금 1.1M → 진척 비율 ≈ 0.856 (부족)
    g = full.details["potential"]["goals"][0]
    assert g["months_left"] == 28 and g["required_monthly"] == 1_285_714
    assert g["coverage"] == pytest.approx(1_100_000 / 1_285_714, abs=0.001)


def test_goal_allocation_follows_priority_order():
    goals = [GoalInfo("우선목표", 30_000_000, 0, date(2027, 8, 7), 1),    # 필요 월 2.5M → 여유 자금을 모두 소진
             GoalInfo("후순위", 12_000_000, 0, date(2027, 8, 7), 2)]
    r = compute(EngineInput(AS_OF, _flows(), _holdings(), OnboardingInfo(), goals))
    rows = {g["name"]: g for g in r.details["potential"]["goals"]}
    assert rows["우선목표"]["allocated"] == 1_100_000 and rows["후순위"]["allocated"] == 0
    assert rows["후순위"]["coverage"] == 0.0


def test_spending_control_curve_reduces_score_for_heavy_variable_spending():
    heavy = compute(EngineInput(AS_OF, _flows(essential_var=1_200_000, other_var=1_200_000), _holdings()))
    light = compute(EngineInput(AS_OF, _flows(), _holdings()))
    assert heavy.details["health"]["components"]["spending"]["points"] < \
        light.details["health"]["components"]["spending"]["points"]
