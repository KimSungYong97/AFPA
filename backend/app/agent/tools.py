"""에이전트가 쓰는 도구 모음 — 모두 조회·계산 전용이며 상태를 바꾸지 않는다

변화 감시 에이전트와 대화 에이전트가 함께 쓴다. 도구 결과의 숫자는 사람이 읽는 문자열로 미리 만들어
(예: "1,162,960원", "2029년 2월") 에이전트의 문장 속 수치를 검증할 때 근거가 되게 한다.
"""
import json
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.planner import candidates as cand_engine
from app.services import planner_service as ps


class Ctx:
    def __init__(self, db: Session, user_id: int, today: Optional[date] = None,
                 changes: Optional[List[dict]] = None, events: Optional[List[dict]] = None):
        self.db, self.user_id, self.today = db, user_id, today
        self.changes, self.events = changes or [], events or []


def won(v: float) -> str:
    return f"{round(v):,}원"


def ym(d: Optional[date]) -> str:
    return "달성 어려움" if d is None else f"{d.year}년 {d.month}월"


def _d(s: Optional[str]) -> Optional[date]:
    return date.fromisoformat(s) if s else None


def _kdate(s: str) -> str:
    d = date.fromisoformat(s)
    return f"{d.month}월 {d.day}일"


def scenario_rows(c: Ctx, spec: dict) -> List[dict]:
    res = ps.scenarios_view(c.db, c.user_id, [spec])
    rows = []
    for r in res["scenarios"][0]["effects"]:
        ms = r["months_saved"]
        eff = ("기한 내 달성이 가능해짐" if r["makes_reachable"] else "기한 내 달성이 어려워짐" if r["becomes_unreachable"]
               else f"{abs(ms)}개월 {'앞당겨짐' if ms > 0 else '늦어짐'}" if ms else "변화 없음")
        rows.append({"goal": r["goal"], "now": ym(_d(r["base_completion"])), "after": ym(_d(r["new_completion"])), "effect": eff})
    return rows


# ---------------------------------------------------------------- 도구 ----
def tool_get_profile_changes(c: Ctx, **_) -> dict:
    """지난번 확인 이후 달라진 금융 프로필 항목(소득·여유 자금·순자산·점수 등)을 조회한다."""
    if not c.changes:
        return {"changes": [], "note": "눈에 띄게 달라진 프로필 항목이 없어요."}
    return {"changes": [{"id": x["id"], "text": x["text"]} for x in c.changes]}


def tool_get_spending_events(c: Ctx, **_) -> dict:
    """카테고리별 소비 변화·월중 전망 경고 이벤트를 조회한다."""
    if not c.events:
        return {"events": [], "note": "감지된 소비 변화가 없어요."}
    label = {"structural": "구조적(지속될 변화)", "forecast": "월중 전망 경고", "outcome": "실천 결과 보고"}
    return {"events": [{"id": e["id"], "judgement": label.get(e["judgement"], "일시적"), "text": e["message"]} for e in c.events]}


def tool_get_plan_status(c: Ctx, **_) -> dict:
    """현재 계획과 지금 상황을 비교한다: 계획 변경이 필요한지(코드 판정), 목표별 달성 예상 시기 변화."""
    import json as _json
    plan = ps.active_plan(c.db, c.user_id)
    if plan is None:
        return {"has_plan": False, "plan_change_needed": False, "note": "아직 만들어진 계획이 없어요."}
    ctx = ps.build_context(c.db, c.user_id, exclude_adopted=False)
    dev = ps.deviation(c.db, c.user_id, ctx)
    base = _json.loads(plan.baseline_json or "{}")
    goals = []
    for g in base.get("goals", []):
        now = ctx.base.goal(g["name"])
        old = _d(g.get("completion_date"))
        new = now.completion_date if now else None
        delay = (new.year - old.year) * 12 + (new.month - old.month) if old and new else None
        goals.append({"goal": g["name"], "planned": ym(old), "now": ym(new),
                      "delay": None if delay is None else (f"{abs(delay)}개월 {'늦어짐' if delay > 0 else '빨라짐'}" if delay else "변화 없음")})
    return {"has_plan": True, "plan_change_needed": dev is not None,
            "reason": dev["message"] if dev else "계획과 큰 차이가 없어요.",
            "budget_in_plan": won(plan.budget_at_plan), "budget_now": won(ctx.budget), "goals": goals}


def tool_get_goal_status(c: Ctx, **_) -> dict:
    """내 목표별 현재 상황: 목표 금액·기한, 지금 속도로 갈 때 달성 예상 시기, 기한 대비 차이."""
    ctx = ps.build_context(c.db, c.user_id, exclude_adopted=False)
    rows = []
    for g in ctx.base.goals:
        gap = g.gap_months
        rows.append({"goal": g.name, "target": won(g.target_amount), "deadline": ym(g.target_date) if g.target_date else "기한 없음",
                     "expected": ym(g.completion_date),
                     "vs_deadline": None if gap is None else (f"기한보다 {abs(gap)}개월 늦어요" if gap > 0 else f"기한보다 {abs(gap)}개월 여유가 있어요" if gap < 0 else "기한에 맞아요"),
                     "monthly_budget": won(ctx.budget)})
    return {"goals": rows}


def tool_get_recommended_actions(c: Ctx, **_) -> dict:
    """지금 상황에서 효과가 큰 순서의 대응 행동 후보 3개를 조회한다(효과는 코드가 계산한 값)."""
    ctx = ps.build_context(c.db, c.user_id)
    cands = cand_engine.generate(ctx.cand_ctx)
    top = [x for x in cands if x["mandatory"]] + [x for x in cands if not x["mandatory"]][:3]
    rows = []
    for i, x in enumerate(top[:3], 1):
        e = x["effect"]
        ms = e.get("months_saved")
        eff = ("목표 달성이 가능해짐" if e.get("makes_reachable")
               else f"목표 달성이 {abs(ms)}개월 {'앞당겨짐' if ms > 0 else '늦어짐'}" if ms
               else f"연 {e.get('annual_saving', 0):,}원 절약")
        rows.append({"rank": i, "title": x["title"], "monthly": f"월 {won(abs(x['monthly_saving']))}",
                     "effect": eff, "mandatory": bool(x["mandatory"])})
    return {"actions": rows}


def tool_get_outcome_report(c: Ctx, **_) -> dict:
    """지금까지 실천한 제안의 실제 결과: 얼마나 아꼈는지, 그 덕분에 목표 달성이 얼마나 빨라졌는지, 아직 확인 못 한 제안."""
    from app.services import feedback_service
    r = feedback_service.outcome_report(c.db, c.user_id)
    if not r["has_plan"]:
        return {"note": r["headline"]}
    state = {"achieved": "잘 지키고 있어요", "partial": "일부 지키고 있어요", "not_yet": "아직 효과가 없어요",
             "self_reported": "직접 완료로 표시했어요", "waiting": "다음 달 데이터를 기다리는 중이에요"}
    return {"summary": r["headline"], "realized_monthly": won(r["realized_monthly"]),
            "items": [{"title": i["title"], "state": state.get(i["state"], i["state"]),
                       "target": f"월 {won(i['expected'])}", "actual": None if i["actual"] is None else f"월 {won(i['actual'])}"}
                      for i in r["items"]]}


def tool_get_category_spending(c: Ctx, **_) -> dict:
    """카테고리별 월평균 변동지출(최근 완결 월 기준). '○○ 지출을 줄이면' 질문 전에 규모를 볼 때 쓴다."""
    ctx = ps.build_context(c.db, c.user_id, exclude_adopted=False)
    n = max(len(ctx.window), 1)
    rows = sorted(({"category": cat, "monthly_avg": won(sum(v.get(m, 0) for m in ctx.window) / n)}
                   for cat, v in ctx.category_monthly.items() if cat != "미분류"),
                  key=lambda r: -int(r["monthly_avg"].replace(",", "").replace("원", "")))
    return {"categories": rows[:10]}


def tool_what_if_save_more(c: Ctx, monthly_amount: float = 0, **_) -> dict:
    """매달 저축을 monthly_amount원 더(음수면 덜) 하면 각 목표 달성 시기가 어떻게 바뀌는지 계산한다."""
    try:
        amt = float(monthly_amount)
        rows = scenario_rows(c, {"kind": "save_delta", "label": f"월 {round(amt):,}원 추가 저축", "delta": amt})
    except Exception as e:  # noqa: BLE001 - 범위 오류 등을 돌려줘 다시 시도하게 한다
        return {"error": str(e)}
    return {"scenario": f"월 {won(amt)} 추가 저축", "goals": rows}


def tool_what_if_cut_spending(c: Ctx, category: str = "", percent: float = 0, **_) -> dict:
    """특정 소비 카테고리의 월평균 지출을 percent% 줄이면 목표 달성 시기가 어떻게 바뀌는지 계산한다."""
    ctx = ps.build_context(c.db, c.user_id, exclude_adopted=False)
    months = ctx.category_monthly.get(category)
    if not months:
        return {"error": f"'{category}' 카테고리의 지출 내역이 없어요. get_category_spending으로 카테고리를 확인하세요."}
    if not (0 < percent <= 100):
        return {"error": "줄이는 비율은 0 초과 100 이하여야 해요."}
    avg = sum(months.get(m, 0) for m in ctx.window) / max(len(ctx.window), 1)
    cut = avg * percent / 100
    rows = scenario_rows(c, {"kind": "save_delta", "label": f"{category} {percent:g}% 절감", "delta": cut})
    return {"scenario": f"{category} 월평균 {won(avg)}을 {percent:g}% 줄이면 매달 {won(cut)} 더 저축", "goals": rows}


def tool_what_if_one_time_expense(c: Ctx, amount: float = 0, months_later: int = 1, **_) -> dict:
    """months_later개월 뒤에 amount원을 한 번 쓰면(예: 여행·가전 구매) 목표 달성 시기가 어떻게 바뀌는지 계산한다."""
    try:
        rows = scenario_rows(c, {"kind": "expense", "label": "일회성 지출", "month": int(months_later), "amount": float(amount)})
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    return {"scenario": f"{int(months_later)}개월 뒤 {won(float(amount))} 지출", "goals": rows}


def resolve_goal(c: Ctx, name: str) -> Tuple[Optional[str], Optional[str]]:
    """사용자·AI가 부른 목표 이름을 실제 목표 이름으로 찾는다: 정확히 일치 → 한쪽이 다른 쪽을 포함(유일할 때만).
    반환 (이름, 오류). 모호하거나 없으면 오류에 선택 가능한 이름을 담아 다시 시도하게 한다."""
    ctx = ps.build_context(c.db, c.user_id, exclude_adopted=False)
    names = [g.name for g in ctx.path_input.goals]
    key = (name or "").strip()
    if key in names:
        return key, None
    near = [n for n in names if key and (key in n or n in key)]
    if len(near) == 1:
        return near[0], None
    pick = near or names
    return None, f"목표를 찾을 수 없어요: '{name}'. 선택할 수 있는 목표: {', '.join(pick)}"


def tool_what_if_goal_shift(c: Ctx, goal: str = "", shift_months: int = 0, new_target_amount: float = 0, **_) -> dict:
    """목표(goal 이름)의 기한을 shift_months개월 미루거나(양수)/당기거나(음수), 목표 금액을 바꾸면 달성 가능성이 어떻게 바뀌는지 계산한다."""
    real, err = resolve_goal(c, goal)
    if err:
        return {"error": err}
    try:
        rows = scenario_rows(c, {"kind": "goal", "label": "목표 조정", "goal": real, "shift_months": int(shift_months),
                                 "amount": float(new_target_amount)})
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    return {"scenario": f"'{real}' 목표 조정", "goals": rows}


def tool_get_cash_forecast(c: Ctx, **_) -> dict:
    """이번 달 소비 속도로 월말까지 가면 어떻게 되는지 전망한다: 예상 지출, 월중 최저 현금과 날짜, 월말 예상 잔액, 위험도."""
    f = ps.cash_forecast(c.db, c.user_id)
    if f["status"] != "ok":
        return {"note": f.get("note", "전망을 만들 수 없어요.")}
    risk = {"ok": "안전", "watch": "주의", "danger": "위험(현금이 바닥날 수 있어요)"}[f["risk"]]
    return {
        "month": f["month"], "risk": risk,
        "spent_so_far": won(f["spent_so_far"]), "projected_variable": won(f["projected_variable"]),
        "usual_variable": won(f["baseline_variable"]),
        "vs_usual": (f"평소보다 {won(abs(f['overspend']))} 더 쓸 것 같아요" if f["overspend"] > 0
                     else f"평소보다 {won(abs(f['overspend']))} 덜 쓸 것 같아요"),
        "overspent_categories": [f"{x['category']}: 평소 {won(x['baseline'])} → 이번 달 예상 {won(x['projected'])} ({x['over_pct']}% 초과)"
                                 for x in f["overspent_categories"]],
        "cash_now": won(f["cash_now"]), "lowest_cash": f"{_kdate(f['min_cash_date'])}쯤 {won(f['min_cash'])}",
        "month_end_cash": won(f["end_cash"]),
        "upcoming": [f"{_kdate(e['date'])} {e['name']} {won(e['amount'])} ({e['kind']})" for e in f["upcoming"][:6]],
    }


# ---------------------------------------------------------------- 레지스트리 ----
# 이름 → (함수, 인자 스키마). 인자가 없으면 빈 dict
_P = {"type": "number"}
TOOLS: Dict[str, Tuple[Callable, dict]] = {
    "get_profile_changes": (tool_get_profile_changes, {}),
    "get_spending_events": (tool_get_spending_events, {}),
    "get_plan_status": (tool_get_plan_status, {}),
    "get_goal_status": (tool_get_goal_status, {}),
    "get_recommended_actions": (tool_get_recommended_actions, {}),
    "get_category_spending": (tool_get_category_spending, {}),
    "get_cash_forecast": (tool_get_cash_forecast, {}),
    "get_outcome_report": (tool_get_outcome_report, {}),
    "what_if_save_more": (tool_what_if_save_more, {"monthly_amount": {**_P, "description": "매달 추가로 저축할 금액(원). 줄이려면 음수."}}),
    "what_if_cut_spending": (tool_what_if_cut_spending, {
        "category": {"type": "string", "description": "소비 카테고리 이름(예: 쇼핑, 식비, 카페/간식)"},
        "percent": {**_P, "description": "줄일 비율(%)"}}),
    "what_if_one_time_expense": (tool_what_if_one_time_expense, {
        "amount": {**_P, "description": "한 번에 쓸 금액(원)"}, "months_later": {**_P, "description": "몇 개월 뒤에 쓰는지"}}),
    "what_if_goal_shift": (tool_what_if_goal_shift, {
        "goal": {"type": "string", "description": "목표 이름"},
        "shift_months": {**_P, "description": "기한을 미룰 개월 수(양수) 또는 당길 개월 수(음수)"},
        "new_target_amount": {**_P, "description": "바꿀 목표 금액(원). 안 바꾸면 0"}}),
}


def schemas(names: List[str]) -> List[dict]:
    return [{"type": "function", "function": {
        "name": n, "description": TOOLS[n][0].__doc__,
        "parameters": {"type": "object", "properties": TOOLS[n][1], "required": list(TOOLS[n][1])}}} for n in names]


def execute(c: Ctx, name: str, args: dict, allowed: List[str]) -> str:
    if name not in allowed or name not in TOOLS:
        return json.dumps({"error": f"쓸 수 없는 도구: {name}"}, ensure_ascii=False)
    try:
        return json.dumps(TOOLS[name][0](c, **args), ensure_ascii=False)
    except TypeError:
        return json.dumps({"error": "도구 인자가 올바르지 않아요."}, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": str(e)}, ensure_ascii=False)
