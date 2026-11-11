"""시나리오 엔진 (What-if) — 기준 경로 대비 차이로 표시한다

시나리오 종류 (설계 3절):
  save_delta  저축 변경      월 배분액 ±N원
  expense     지출 이벤트    N개월 뒤 일회성 지출 M원
  income      소득 변화      월 수입 ±N원
  goal        목표 변경      기한 연기/단축, 금액 변경
  return      수익률 가정    conservative / base / optimistic
사용자가 입력하는 값은 범위를 검증한다(음수·비현실 값 차단).
"""
from copy import deepcopy
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.pipeline import params
from app.planner.path import PathInput, PathResult, add_months, compare, net_worth_at, simulate

SCENARIO_KINDS = {"save_delta", "expense", "income", "goal", "return"}


class ScenarioError(ValueError):
    pass


@dataclass
class Scenario:
    kind: str
    label: str = ""
    delta: float = 0.0                 # save_delta / income: 월 증감액
    month: int = 1                     # expense: 몇 개월 뒤
    amount: float = 0.0                # expense: 지출액 / goal: 새 목표 금액
    goal: Optional[str] = None         # goal: 대상 목표 이름
    shift_months: int = 0              # goal: 기한 이동(+연기, −단축)
    case: str = "base"                 # return


def validate(sc: Scenario, base: PathInput, monthly_income: Optional[float]) -> None:
    if sc.kind not in SCENARIO_KINDS:
        raise ScenarioError(f"알 수 없는 시나리오 종류: {sc.kind}")
    cap = max(monthly_income or 0, abs(base.monthly_budget), 1_000_000) * 2   # 비현실적으로 큰 값 차단
    if sc.kind in ("save_delta", "income"):
        if abs(sc.delta) > cap:
            raise ScenarioError(f"월 증감액은 ±{cap:,.0f}원 이내여야 합니다.")
        if sc.kind == "save_delta" and base.monthly_budget + sc.delta < -cap:
            raise ScenarioError("월 배분액이 비현실적으로 작아집니다.")
    elif sc.kind == "expense":
        if not (1 <= sc.month <= 120):
            raise ScenarioError("지출 시점은 1~120개월 사이여야 합니다.")
        if not (0 < sc.amount <= 1_000_000_000):
            raise ScenarioError("지출 금액은 0원 초과 10억 원 이하여야 합니다.")
    elif sc.kind == "goal":
        if not any(g.name == sc.goal for g in base.goals):
            raise ScenarioError(f"목표를 찾을 수 없습니다: {sc.goal}")
        if not (-120 <= sc.shift_months <= 240):
            raise ScenarioError("기한 이동은 −120~+240개월 사이여야 합니다.")
        if sc.amount < 0 or sc.amount > 100_000_000_000:
            raise ScenarioError("목표 금액이 범위를 벗어났습니다.")
    elif sc.kind == "return":
        if sc.case not in params.RETURN_ASSUMPTIONS:
            raise ScenarioError(f"수익률 가정은 {', '.join(params.RETURN_ASSUMPTIONS)} 중 하나여야 합니다.")


def apply(sc: Scenario, base: PathInput) -> PathInput:
    inp = deepcopy(base)
    if sc.kind in ("save_delta", "income"):
        inp.monthly_budget += sc.delta
    elif sc.kind == "expense":
        inp.one_offs = dict(inp.one_offs)
        inp.one_offs[sc.month] = inp.one_offs.get(sc.month, 0.0) + sc.amount
    elif sc.kind == "goal":
        for g in inp.goals:
            if g.name == sc.goal:
                if sc.amount > 0:
                    g.target_amount = sc.amount
                if sc.shift_months and g.target_date:
                    g.target_date = add_months(g.target_date, sc.shift_months)
    elif sc.kind == "return":
        inp.annual_return = params.RETURN_ASSUMPTIONS[sc.case]
    return inp


def default_label(sc: Scenario) -> str:
    if sc.label:
        return sc.label
    if sc.kind == "save_delta":
        return f"월 저축 {sc.delta:+,.0f}원"
    if sc.kind == "income":
        return f"월 소득 {sc.delta:+,.0f}원"
    if sc.kind == "expense":
        return f"{sc.month}개월 뒤 {sc.amount:,.0f}원 지출"
    if sc.kind == "goal":
        parts = []
        if sc.shift_months:
            parts.append(f"기한 {sc.shift_months:+d}개월")
        if sc.amount:
            parts.append(f"금액 {sc.amount:,.0f}원")
        return f"{sc.goal}: " + ", ".join(parts)
    return {"conservative": "수익률 보수", "base": "수익률 기준", "optimistic": "수익률 낙관"}[sc.case]


def run_scenarios(base_input: PathInput, base_result: PathResult, scenarios: List[Scenario],
                  monthly_income: Optional[float] = None, compare_months: int = 60) -> List[dict]:
    """시나리오 최대 3개를 기준 경로와 나란히 비교한다."""
    if len(scenarios) > params.MAX_SCENARIOS:
        raise ScenarioError(f"시나리오는 최대 {params.MAX_SCENARIOS}개까지 비교할 수 있습니다.")
    out = []
    base_nw = net_worth_at(base_result, compare_months)
    for sc in scenarios:
        validate(sc, base_input, monthly_income)
        res = simulate(apply(sc, base_input))
        nw = net_worth_at(res, compare_months)
        out.append({
            "label": default_label(sc), "kind": sc.kind,
            "goals": compare(base_result, res),
            "paths": res,
            "net_worth_diff": None if nw is None or base_nw is None else nw - base_nw,
            "compare_months": compare_months,
        })
    return out
