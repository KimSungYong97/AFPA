"""행동 후보 순위 엔진 (2차: 새는 돈 줄이기 + 보유 자산 간 조정)

모든 후보를 "목표 달성 단축 기간"이라는 하나의 기준으로 환산해 효과 큰 순서로 정렬한다.
- 단독 효과: 후보 하나를 기준 경로에 적용한 결과(후보끼리 단순 합산하지 않는다)
- 충돌 표시: 같은 conflict_group(예: 같은 카테고리의 두 절감안)은 함께 하기 어렵다고 표시
- 조합 효과: 여러 후보를 고르면 조합 전체를 경로에 다시 적용해 계산한다(combine)
- 선처리: 비상금 충당률이 100% 미만이면(R-01) 비상금 우선 적립을 최우선·필수로 두고 투자 후보는 내지 않는다
순위와 효과는 모두 코드가 계산하며, LLM은 순위의 이유를 설명할 뿐이다.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.pipeline import params
from app.planner.path import PathInput, PathResult, compare, simulate, with_budget


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


# ---------------------------------------------------------------------------
# 후보 생성
# ---------------------------------------------------------------------------
def generate(ctx: CandidateContext) -> List[dict]:
    cands: List[dict] = []
    income = ctx.monthly_income or 0
    min_saving = max(params.G_MIN_SAVING_ABS, income * params.G_MIN_SAVING_INCOME_SHARE)

    # 1) 카테고리 절감 — 비필수 카테고리는 평균의 15%, 이상 지출은 직전 평균 수준으로 복구
    outlier_by_cat = {o["category"]: o for o in ctx.outliers}
    for cat, by_month in ctx.category_monthly.items():
        if cat == "미분류":                      # 분류가 확정되지 않은 지출은 절감 후보로 삼지 않는다(분류 확인이 먼저)
            continue
        vals = [by_month.get(m, 0.0) for m in ctx.window]
        avg = sum(vals) / len(vals) if vals else 0.0
        if cat in params.G_NONESSENTIAL and avg > 0:
            saving = round(avg * params.G_CUT_RATE_NONESSENTIAL, -2)
            if saving >= min_saving:
                cands.append(_cand(
                    f"cut:{cat}", "소비 절감", f"{cat} 지출 {int(params.G_CUT_RATE_NONESSENTIAL * 100)}% 줄이기",
                    f"{cat} 월 평균 {avg:,.0f}원 중 {saving:,.0f}원을 줄입니다.", saving,
                    {"kind": "category_cut", "category": cat, "baseline_avg": round(avg),
                     "cut_rate": params.G_CUT_RATE_NONESSENTIAL},
                    {"월 평균 지출": round(avg), "관측 개월": len(vals)}, f"cat:{cat}"))
        o = outlier_by_cat.get(cat)
        if o:
            saving = round(o["recent"] - o["baseline"], -2)
            if saving >= min_saving:
                cands.append(_cand(
                    f"restore:{cat}", "소비 절감", f"{cat} 급증분 되돌리기",
                    f"{cat}이 직전 3개월 평균 {o['baseline']:,.0f}원에서 {o['recent']:,.0f}원으로 늘었습니다. "
                    f"평균 수준으로 되돌리면 월 {saving:,.0f}원을 아낍니다.", saving,
                    {"kind": "category_cut", "category": cat, "baseline_avg": round(o["baseline"]),
                     "restore": True},
                    {"최근 월": round(o["recent"]), "직전 3개월 평균": round(o["baseline"]),
                     "증가율(%)": o.get("growth_pct")}, f"cat:{cat}"))

    # 2) 구독 정리 — 미사용 여부는 데이터로 알 수 없으므로 사용자 확인이 필요하다
    for sub in ctx.subscriptions:
        amt = round(sub["monthly_amount"], -2)
        if amt >= params.G_MIN_SAVING_ABS:
            cands.append(_cand(
                f"sub:{sub['merchant']}", "구독 정리", f"구독 '{sub['merchant']}' 점검",
                f"매월 {amt:,.0f}원이 나가는 정기결제입니다. 쓰지 않는다면 해지해 보세요(사용 여부는 직접 확인 필요).",
                amt, {"kind": "subscription", "merchant": sub["merchant"], "monthly_amount": amt},
                {"월 결제액": amt}, f"sub:{sub['merchant']}"))

    # 3) 보유 자산 간 조정 (R-01): 비상금 우선 / 과다 현금 이동
    em = ctx.emergency or {}
    coverage = em.get("coverage_ratio")
    mandatory: List[dict] = []
    budget = ctx.path_input.monthly_budget
    if budget < 0:
        mandatory.append(_cand(
            "deficit", "저축 금액 조정", "월 적자부터 해소하기",
            f"매달 {-budget:,.0f}원 적자입니다. 저축·목표 배분보다 먼저 아래 절감안으로 적자를 메워야 합니다.",
            0.0, {"kind": "deficit_first", "deficit": round(-budget)},
            {"월 적자": round(-budget)}, "budget", mandatory=True))
    if coverage is not None and coverage < 100 and em.get("required") and budget > 0:
        import math
        shortage = em["required"] - em.get("liquid_cash", 0)
        monthly = round(min(shortage / params.G_EMERGENCY_FILL_MONTHS, budget), -2)
        monthly = max(monthly, 1_000)
        months = min(math.ceil(shortage / monthly), 60)
        mandatory.append(_cand(
            "emergency", "비상금 우선 적립", "비상금 먼저 채우기",
            f"비상금이 {shortage:,.0f}원 부족합니다(충당률 {coverage:.1f}%). 투자·장기 적립보다 먼저, "
            f"월 {monthly:,.0f}원씩 {months}개월 동안 입출금·CMA에 모아 두세요.",
            -monthly, {"kind": "emergency_first", "shortage": round(shortage), "monthly": monthly,
                       "months": months},
            {"충당률(%)": coverage, "필요 비상금": em["required"], "보유 현금성": em.get("liquid_cash", 0)},
            "budget", mandatory=True))
    elif coverage is not None and coverage >= 100:
        excess = em.get("liquid_cash", 0) - em.get("required", 0) - em.get("monthly_essential_expense", 0)
        if excess >= params.G_CASH_EXCESS_MIN:
            gain = round(excess * (params.G_DEPOSIT_RATE - params.G_CHECKING_RATE) / 12, -2)
            if gain > 0:
                cands.append(_cand(
                    "cash_move", "자산 비중 조정", "남는 현금을 저축성 자산으로 옮기기",
                    f"비상금과 한 달 생활비를 뺀 현금 {excess:,.0f}원이 입출금에 있습니다. "
                    f"저축성 자산으로 옮기면 월 약 {gain:,.0f}원의 이자를 더 받습니다(금리 가정 기준).",
                    gain, {"kind": "cash_move", "excess": round(excess)},
                    {"이동 대상 금액": round(excess), "금리 가정": f"{params.G_CHECKING_RATE:.1%} → {params.G_DEPOSIT_RATE:.1%}"},
                    "cash"))

    cands = [c for c in cands if c["key"] not in ctx.exclude_keys]
    cands = _apply_effects(ctx, cands)
    cands = _mark_conflicts(cands)
    ranked = _rank(cands)
    for c in mandatory:
        if c["key"] in ctx.exclude_keys:
            continue
        _apply_effects(ctx, [c])
    return [c for c in mandatory if c["key"] not in ctx.exclude_keys] + ranked


def _cand(key, action_type, title, description, monthly_saving, params_, evidence, group,
          mandatory: bool = False) -> dict:
    return {
        "key": key, "action_type": action_type, "title": title, "description": description,
        "monthly_saving": float(monthly_saving), "params": params_, "evidence": evidence,
        "conflict_group": group, "conflicts_with": [], "mandatory": mandatory, "effect": None,
    }


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
        inp = _candidate_input(base_in, c)
        res = simulate(inp)
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


def _candidate_input(base_in: PathInput, c: dict) -> PathInput:
    if c["params"].get("kind") == "emergency_first":
        inp = with_budget(base_in, 0)
        inp.one_offs = dict(inp.one_offs)
        for k in range(1, c["params"]["months"] + 1):
            inp.one_offs[k] = inp.one_offs.get(k, 0.0) + c["params"]["monthly"]
        return inp
    return with_budget(base_in, c["monthly_saving"])


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
    inp = with_budget(ctx.path_input, sum(c["monthly_saving"] for c in chosen
                                          if c["params"].get("kind") != "emergency_first"))
    inp.one_offs = dict(inp.one_offs)
    for c in chosen:
        if c["params"].get("kind") == "emergency_first":
            for k in range(1, c["params"]["months"] + 1):
                inp.one_offs[k] = inp.one_offs.get(k, 0.0) + c["params"]["monthly"]
    res = simulate(inp)
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
