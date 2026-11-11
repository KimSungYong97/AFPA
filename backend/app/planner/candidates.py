"""행동 후보 순위 엔진

모든 후보를 "목표 달성 단축 기간"이라는 하나의 기준으로 환산해 효과 큰 순서로 정렬한다.
- 후보는 **공급자(provider)** 가 올린다(registry). 2차는 소비 절감·구독 정리·자산 조정이고, 3차 이후 예·적금·대출·투자 모듈이 같은 방식으로 꽂힌다.
- 후보를 올리기 전에 **규칙 판정기(rule checker)** 가 "이 사용자가 실제로 할 수 있는가"를 거른다(3차 규제·제도 엔진). 걸러진 후보와 이유는 따로 돌려준다.
- 단독 효과: 후보 하나의 `change`를 기준 경로에 적용한 결과(후보끼리 단순 합산하지 않는다)
- 충돌 표시: 같은 conflict_group(예: 같은 카테고리의 두 절감안)은 함께 하기 어렵다고 표시
- 조합 효과: 여러 후보의 change를 합쳐 경로를 다시 계산한다(combine)
- 필수 선처리: 비상금 충당률이 100% 미만이면(R-01) 비상금 우선 적립을 최우선·필수로 두고 투자 후보는 내지 않는다
순위와 효과는 모두 코드가 계산하며, LLM은 순위의 이유를 설명할 뿐이다.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.planner import registry
from app.planner.path import PathInput, PathResult, apply_change, compare, merge_changes, simulate


@dataclass
class CandidateContext:
    path_input: PathInput
    monthly_income: Optional[float]
    category_monthly: Dict[str, Dict[str, float]]      # 변동지출 {카테고리: {'YYYY-MM': 금액}} (관측 기간)
    window: List[str]                                  # 관측 완결 월 ['2026-03', ...]
    subscriptions: List[dict] = field(default_factory=list)   # [{merchant, monthly_amount}]
    outliers: List[dict] = field(default_factory=list)        # 엔진의 이상 지출 [{category, recent, baseline}]
    emergency: dict = field(default_factory=dict)             # 비상금 엔진 결과
    exclude_keys: set = field(default_factory=set)            # 이미 수락·완료된 후보
    facts: dict = field(default_factory=dict)                 # 규칙 판정에 쓰는 사용자 사실(나이·고용·소득·거주 형태 등)
    prefs: dict = field(default_factory=dict)                 # 거절 학습 결과: {"cut_scale": {카테고리: 배율}}


def make_candidate(key: str, action_type: str, title: str, description: str, monthly_saving: float,
                   params_: dict, evidence: dict, group: str, mandatory: bool = False,
                   change: Optional[dict] = None, provider: str = "") -> dict:
    """공급자가 후보를 만드는 표준 형식.

    key            후보 식별자(안정적이어야 한다: 수락·거절 이력이 이 키에 붙는다)
    monthly_saving 사용자에게 보여 줄 월 절감·이득 금액(참고용, 효과 계산은 change로 한다)
    params_/evidence 후보 유형별 세부 값, 근거 수치(화면·추적에 쓴다)
    group          같은 group의 후보는 서로 충돌한다(함께 하기 어렵다)
    change         경로를 바꾸는 방식. 생략하면 {"monthly_delta": monthly_saving}
    """
    return {
        "key": key, "action_type": action_type, "title": title, "description": description,
        "monthly_saving": float(monthly_saving), "params": params_, "evidence": evidence,
        "conflict_group": group, "conflicts_with": [], "mandatory": mandatory, "effect": None,
        "change": change if change is not None else {"monthly_delta": float(monthly_saving)},
        "provider": provider,
    }


# ---------------------------------------------------------------------------
# 후보 생성
# ---------------------------------------------------------------------------
def generate_report(ctx: CandidateContext) -> dict:
    """{"candidates": [...순위순, 필수 먼저], "excluded": [{key, title, rule_id, reason}]}"""
    raw: List[dict] = []
    for p in registry.providers():
        raw += p.generate(ctx)
    raw = [c for c in raw if c["key"] not in ctx.exclude_keys]

    eligible, excluded = [], []
    for c in raw:
        verdict = _check_rules(c, ctx.facts)
        if verdict is None:
            eligible.append(c)
        else:
            excluded.append({"key": c["key"], "title": c["title"], "rule_id": verdict.rule_id, "reason": verdict.reason})

    mandatory = [c for c in eligible if c["mandatory"]]
    optional = [c for c in eligible if not c["mandatory"]]
    _apply_effects(ctx, mandatory + optional)
    ranked = _rank(_mark_conflicts(optional))
    return {"candidates": mandatory + ranked, "excluded": excluded}


def generate(ctx: CandidateContext) -> List[dict]:
    return generate_report(ctx)["candidates"]


def _check_rules(cand: dict, facts: dict):
    for checker in registry.checkers():
        v = checker.check(cand, facts)
        if not v.ok:
            return v
    return None


# ---------------------------------------------------------------------------
# 효과 계산 / 정렬 / 충돌
# ---------------------------------------------------------------------------
def _headline_goal(base: PathResult) -> Optional[str]:
    for g in sorted(base.goals, key=lambda g: g.priority):
        if g.status != "done":
            return g.name
    return None


def _apply_effects(ctx: CandidateContext, cands: List[dict]) -> List[dict]:
    base_in = ctx.path_input
    base = simulate(base_in)
    head = _headline_goal(base)
    for c in cands:
        res = simulate(apply_change(base_in, c["change"]))
        per_goal = compare(base, res)
        h = next((p for p in per_goal if p["goal"] == head), None)
        c["effect"] = {
            "headline_goal": head,
            "months_saved": h["months_saved"] if h else None,
            "makes_reachable": h["makes_reachable"] if h else False,
            "base_completion": h["base_completion"].isoformat() if h and h["base_completion"] else None,
            "new_completion": h["new_completion"].isoformat() if h and h["new_completion"] else None,
            "shortfall_change": h["shortfall_change"] if h else None,
            "annual_saving": round(max(c["monthly_saving"], 0) * 12),
            "deficit_closed_pct": _deficit_closed(base_in.monthly_budget, c["monthly_saving"]),
            "per_goal": [{**p, "base_completion": p["base_completion"].isoformat() if p["base_completion"] else None,
                          "new_completion": p["new_completion"].isoformat() if p["new_completion"] else None}
                         for p in per_goal],
        }
    return cands


def _deficit_closed(budget: float, saving: float) -> Optional[float]:
    if budget >= 0 or saving <= 0:
        return None
    return round(min(saving / -budget, 1.0) * 100, 1)


def _rank_key(c: dict):
    e = c["effect"]
    if e["makes_reachable"]:
        return (2, c["monthly_saving"])
    if e["months_saved"] is not None and e["months_saved"] > 0:
        return (1, e["months_saved"] + c["monthly_saving"] / 1e9)
    return (0, c["monthly_saving"])


def _rank(cands: List[dict]) -> List[dict]:
    ranked = sorted(cands, key=_rank_key, reverse=True)
    for i, c in enumerate(ranked, 1):
        c["rank"] = i
    return ranked


def _mark_conflicts(cands: List[dict]) -> List[dict]:
    groups: Dict[str, List[dict]] = {}
    for c in cands:
        groups.setdefault(c["conflict_group"], []).append(c)
    for g in groups.values():
        for c in g:
            c["conflicts_with"] = [o["key"] for o in g if o is not c]
    return cands


# ---------------------------------------------------------------------------
# 조합 효과 (단독 효과의 합이 아니라 경로를 다시 계산)
# ---------------------------------------------------------------------------
def combine(ctx: CandidateContext, candidates: List[dict], selected: List[str]) -> dict:
    by_key = {c["key"]: c for c in candidates}
    chosen, ignored = [], []
    used_groups: Dict[str, dict] = {}
    for key in selected:
        c = by_key.get(key)
        if c is None:
            continue
        g = c["conflict_group"]
        if g in used_groups:                      # 충돌: 더 큰 절감액 하나만 채택
            prev = used_groups[g]
            if abs(c["monthly_saving"]) > abs(prev["monthly_saving"]):
                chosen.remove(prev)
                ignored.append(prev["key"])
                chosen.append(c)
                used_groups[g] = c
            else:
                ignored.append(key)
        else:
            chosen.append(c)
            used_groups[g] = c

    base = simulate(ctx.path_input)
    res = simulate(apply_change(ctx.path_input, merge_changes([c["change"] for c in chosen])))
    per_goal = compare(base, res)
    head = _headline_goal(base)
    sum_individual = sum((c["effect"]["months_saved"] or 0) for c in chosen if c["effect"])
    h = next((p for p in per_goal if p["goal"] == head), None)
    return {
        "selected": [c["key"] for c in chosen], "ignored_conflicts": ignored,
        "total_monthly_saving": sum(c["monthly_saving"] for c in chosen if c["monthly_saving"] > 0),
        "headline_goal": head,
        "combined_months_saved": h["months_saved"] if h else None,
        "makes_reachable": h["makes_reachable"] if h else False,
        "sum_of_individual_months_saved": sum_individual,     # 참고용: 합산은 정확하지 않다
        "per_goal": [{**p, "base_completion": p["base_completion"].isoformat() if p["base_completion"] else None,
                      "new_completion": p["new_completion"].isoformat() if p["new_completion"] else None}
                     for p in per_goal],
    }
