"""통합 플래너 서비스 (2차) — 계산 엔진(app/planner)과 DB를 연결한다

  컨텍스트 구성 → 행동 후보 순위 → Action Plan 저장 → 수락/거절 → 이행 추적 → 경로 이탈 감지
  → 재설계 제안(승인 후 적용) → 소비 변화 이벤트 → 알림
모든 수치는 코드(app/planner)가 계산한다. 이 모듈은 저장·상태 전이·알림 규칙만 다룬다.
"""
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.models.entities import (
    ActionItem, Goal, MonitoringEvent, Notification, OneOffMark, PlanVersion,
)
from app.pipeline import params
from app.pipeline.engines import observation_window
from app.planner import candidates as cand_engine
from app.planner import monitoring as mon_engine
from app.planner.candidates import CandidateContext
from app.planner.path import PathGoal, PathInput, PathResult, add_months, compare, simulate
from app.planner.scenarios import Scenario, run_scenarios
from app.services import pipeline_service


# ===========================================================================
# 컨텍스트
# ===========================================================================
@dataclass
class PlannerContext:
    user_id: int
    as_of: date
    window: List[str]
    snapshot: object
    details: dict
    budget: float
    path_input: PathInput
    base: PathResult
    cand_ctx: CandidateContext
    category_monthly: Dict[str, Dict[str, float]]
    fixed_by_merchant: Dict[str, Dict[str, float]]
    income_by_month: Dict[str, float]
    one_off: Set[tuple]


def _ym(m) -> str:
    return f"{m[0]}-{m[1]:02d}"


def adopted_keys(db: Session, user_id: int) -> Set[str]:
    """이미 수락·완료한 후보는 새 제안에서 제외한다."""
    rows = db.query(ActionItem).join(PlanVersion, ActionItem.plan_version_id == PlanVersion.id).filter(
        ActionItem.user_id == user_id, PlanVersion.status == "active",
        ActionItem.status.in_(["ACCEPTED", "DONE"])).all()
    return {r.item_key for r in rows}


def build_context(db: Session, user_id: int, exclude_adopted: bool = True) -> PlannerContext:
    snap = pipeline_service.latest_snapshot(db, user_id)
    if snap is None:
        raise LookupError("프로필이 없습니다. 먼저 마이데이터를 동기화하세요.")
    inp = pipeline_service.load_engine_input(db, user_id)
    details = json.loads(snap.details_json)
    window_m, _ = observation_window(inp.as_of, inp.flows)
    window = [_ym(m) for m in window_m]
    ws = set(window)

    cat_monthly: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    fixed_by_merchant: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    income_by_month: Dict[str, float] = defaultdict(float)
    sub_months: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for f in inp.flows:
        ym = f"{f.occurred_on.year}-{f.occurred_on.month:02d}"
        if ym not in ws:
            continue
        if f.major == "variable" and f.direction == "out":
            cat_monthly[f.category][ym] += f.amount
        elif f.major == "fixed" and f.direction == "out" and f.source in ("card", "efin"):
            fixed_by_merchant[f.counterparty][ym] += f.amount
        elif f.major == "income" and f.recurring:
            income_by_month[ym] += f.amount
    for f in inp.flows:           # 구독서비스 카테고리의 정기결제 (월 평균 결제액)
        ym = f"{f.occurred_on.year}-{f.occurred_on.month:02d}"
        if f.major == "fixed" and f.category == "구독서비스" and ym in ws:
            sub_months[f.counterparty][ym] += f.amount
    subs = [{"merchant": m, "monthly_amount": sum(v.values()) / len(v)} for m, v in sub_months.items()]

    budget = snap.net_cash_flow if snap.net_cash_flow is not None else 0.0
    goals = [PathGoal(g.name, g.target_amount, g.current_amount, g.target_date, g.priority)
             for g in db.query(Goal).filter_by(user_id=user_id).all()]
    path_input = PathInput(as_of=snap.as_of, monthly_budget=budget, goals=goals,
                           annual_return=params.RETURN_ASSUMPTIONS[params.DEFAULT_RETURN_CASE],
                           initial_net_worth=snap.net_worth or 0.0)
    base = simulate(path_input)

    one_off = {(m.category, m.month) for m in db.query(OneOffMark).filter_by(user_id=user_id)}
    cc = CandidateContext(
        path_input=path_input, monthly_income=snap.monthly_income_net,
        category_monthly={c: dict(v) for c, v in cat_monthly.items()},
        window=window, subscriptions=subs,
        outliers=details.get("spending", {}).get("outliers", []),
        emergency=details.get("emergency_fund", {}),
        exclude_keys=adopted_keys(db, user_id) if exclude_adopted else set(),
    )
    return PlannerContext(
        user_id=user_id, as_of=snap.as_of, window=window, snapshot=snap, details=details, budget=budget,
        path_input=path_input, base=base, cand_ctx=cc,
        category_monthly=cc.category_monthly, fixed_by_merchant={k: dict(v) for k, v in fixed_by_merchant.items()},
        income_by_month=dict(income_by_month), one_off=one_off)


# ===========================================================================
# 경로 / 시나리오
# ===========================================================================
def _goal_path_dict(g) -> dict:
    return {
        "name": g.name, "priority": g.priority, "target_amount": g.target_amount,
        "start_amount": g.start_amount, "target_date": g.target_date.isoformat() if g.target_date else None,
        "required_monthly": None if g.required_monthly is None else round(g.required_monthly),
        "first_month_alloc": round(g.first_month_alloc),
        "completion_date": g.completion_date.isoformat() if g.completion_date else None,
        "completion_months": g.completion_k, "gap_months": g.gap_months,
        "shortfall_at_deadline": None if g.shortfall_at_deadline is None else round(g.shortfall_at_deadline),
        "status": g.status,
    }


def _series_dict(res: PathResult, limit: int = params.SERIES_MONTHS) -> List[dict]:
    return [{"k": s["k"], "date": s["date"].isoformat(), "net_worth": round(s["net_worth"]),
             "balances": {n: round(v) for n, v in s["balances"].items()}} for s in res.series[:limit + 1]]


def path_view(db: Session, user_id: int) -> dict:
    """기준 경로 + 개선 경로(제안된 Action Plan 항목을 모두 실행했을 때)"""
    ctx = build_context(db, user_id, exclude_adopted=False)
    plan = active_plan(db, user_id)
    improved_in = ctx.path_input
    extra = 0.0
    if plan:
        extra = sum(i.monthly_saving for i in plan.items if i.status in ("PROPOSED", "ACCEPTED") and i.monthly_saving > 0)
    from app.planner.path import with_budget
    improved = simulate(with_budget(improved_in, extra)) if extra > 0 else None
    return {
        "as_of": ctx.as_of.isoformat(), "monthly_budget": round(ctx.budget),
        "annual_return": ctx.path_input.annual_return, "return_case": params.DEFAULT_RETURN_CASE,
        "base": {"goals": [_goal_path_dict(g) for g in ctx.base.goals], "series": _series_dict(ctx.base)},
        "improved": None if improved is None else {
            "extra_monthly": round(extra), "goals": [_goal_path_dict(g) for g in improved.goals],
            "series": _series_dict(improved), "effects": _compare_dicts(compare(ctx.base, improved))},
    }


def _compare_dicts(rows: List[dict]) -> List[dict]:
    return [{**r, "base_completion": r["base_completion"].isoformat() if r["base_completion"] else None,
             "new_completion": r["new_completion"].isoformat() if r["new_completion"] else None} for r in rows]


def scenarios_view(db: Session, user_id: int, specs: List[dict]) -> dict:
    ctx = build_context(db, user_id, exclude_adopted=False)
    scenarios = [Scenario(**s) for s in specs]
    results = run_scenarios(ctx.path_input, ctx.base, scenarios, ctx.snapshot.monthly_income_net)
    return {
        "as_of": ctx.as_of.isoformat(), "monthly_budget": round(ctx.budget),
        "base": {"goals": [_goal_path_dict(g) for g in ctx.base.goals], "series": _series_dict(ctx.base)},
        "scenarios": [{
            "label": r["label"], "kind": r["kind"], "effects": _compare_dicts(r["goals"]),
            "net_worth_diff": None if r["net_worth_diff"] is None else round(r["net_worth_diff"]),
            "compare_months": r["compare_months"],
            "goals": [_goal_path_dict(g) for g in r["paths"].goals], "series": _series_dict(r["paths"]),
        } for r in results],
    }


# ===========================================================================
# 행동 후보 순위
# ===========================================================================
def ranked_candidates(db: Session, user_id: int) -> dict:
    ctx = build_context(db, user_id)
    cands = cand_engine.generate(ctx.cand_ctx)
    return {"as_of": ctx.as_of.isoformat(), "monthly_budget": round(ctx.budget),
            "headline_goal": cands[0]["effect"]["headline_goal"] if cands else None,
            "candidates": cands}


def combined_effect(db: Session, user_id: int, selected: List[str]) -> dict:
    ctx = build_context(db, user_id)
    cands = cand_engine.generate(ctx.cand_ctx)
    return cand_engine.combine(ctx.cand_ctx, cands, selected)


# ===========================================================================
# Action Plan 저장 · 상태 전이
# ===========================================================================
def active_plan(db: Session, user_id: int) -> Optional[PlanVersion]:
    plan = (db.query(PlanVersion).filter_by(user_id=user_id, status="active")
            .order_by(PlanVersion.version.desc()).first())
    if plan is not None:
        plan.items = db.query(ActionItem).filter_by(plan_version_id=plan.id).order_by(ActionItem.priority).all()
    return plan


def _baseline_summary(ctx: PlannerContext) -> dict:
    return {
        "budget": round(ctx.budget),
        "goals": [{"name": g.name, "completion_date": g.completion_date.isoformat() if g.completion_date else None,
                   "status": g.status, "gap_months": g.gap_months} for g in ctx.base.goals],
        "goals_sig": sorted([g.name, round(g.target_amount), g.target_date.isoformat() if g.target_date else None]
                            for g in ctx.path_input.goals),
    }


def _rationale(c: dict) -> str:
    """추천 이유: 근거 수치와 경로 효과를 코드가 문장으로 조립한다(수치는 모두 계산 결과)."""
    e = c["effect"] or {}
    parts = [f"{k} {v:,}" if isinstance(v, (int, float)) and not isinstance(v, bool) else f"{k} {v}"
             for k, v in c["evidence"].items()]
    text = "근거: " + ", ".join(parts) + "."
    if c["mandatory"]:
        if e.get("months_saved") is not None and e["months_saved"] < 0:
            text += f" 먼저 채우면 '{e['headline_goal']}' 달성이 {-e['months_saved']}개월 늦어지지만 비상시 안전망이 생깁니다."
        return text
    if e.get("makes_reachable"):
        text += f" 이렇게 하면 '{e['headline_goal']}' 달성이 가능해집니다({e['new_completion']})."
    elif e.get("months_saved"):
        text += f" '{e['headline_goal']}' 달성이 {e['months_saved']}개월 앞당겨집니다({e['base_completion']} → {e['new_completion']})."
    elif e.get("deficit_closed_pct"):
        text += f" 매달 부족한 금액의 {e['deficit_closed_pct']}%를 메웁니다."
    else:
        text += f" 연 {e.get('annual_saving', 0):,}원을 아낍니다."
    return text


def generate_plan(db: Session, user_id: int, today: Optional[date] = None) -> dict:
    """Action Plan 생성. 적용 중인 계획이 없으면 v1을 만들고, 있으면 제안 항목만 새로고침한다."""
    today = today or date.today()
    ctx = build_context(db, user_id)
    cands = cand_engine.generate(ctx.cand_ctx)
    chosen = [c for c in cands if c["mandatory"]] + \
             [c for c in cands if not c["mandatory"]][:params.G_TOP_ACTIONS]

    plan = active_plan(db, user_id)
    if plan is None:
        plan = PlanVersion(user_id=user_id, version=1, status="active", trigger="manual", as_of=ctx.as_of,
                           budget_at_plan=ctx.budget, baseline_json=json.dumps(_baseline_summary(ctx), ensure_ascii=False))
        db.add(plan)
        db.flush()
    existing = {i.item_key: i for i in db.query(ActionItem).filter_by(plan_version_id=plan.id)}
    # 아직 응답하지 않은 제안은 최신 순위로 교체한다
    for it in existing.values():
        if it.status == "PROPOSED" and it.item_key not in {c["key"] for c in chosen}:
            it.status = "EXPIRED"
    for rank, c in enumerate(chosen, 1):
        it = existing.get(c["key"])
        if it is not None and it.status != "PROPOSED":
            continue
        if it is None:
            it = ActionItem(user_id=user_id, plan_version_id=plan.id, item_key=c["key"], proposed_on=today)
            db.add(it)
        _fill_item(it, c, rank)
    db.commit()
    return plan_dict(db, user_id)


def _fill_item(it: ActionItem, c: dict, rank: int) -> None:
    it.action_type, it.title, it.description = c["action_type"], c["title"], c["description"]
    it.monthly_saving = c["monthly_saving"]
    it.params_json = json.dumps(c["params"], ensure_ascii=False)
    it.path_effect_json = json.dumps(c["effect"], ensure_ascii=False, default=str)
    it.rationale = _rationale(c)
    it.priority = 0 if c["mandatory"] else rank
    it.mandatory = c["mandatory"]
    kind = c["params"].get("kind")
    it.tracked_by = "auto" if kind in ("category_cut", "subscription") else "user"
    it.status = "PROPOSED" if it.status in (None, "EXPIRED", "PROPOSED") else it.status


def item_dict(it: ActionItem) -> dict:
    return {
        "id": it.id, "key": it.item_key, "action_type": it.action_type, "title": it.title,
        "description": it.description, "monthly_saving": round(it.monthly_saving),
        "path_effect": json.loads(it.path_effect_json or "{}"), "rationale": it.rationale,
        "priority": it.priority, "mandatory": it.mandatory, "status": it.status, "tracked_by": it.tracked_by,
        "accepted_on": it.accepted_on.isoformat() if it.accepted_on else None,
        "progress": json.loads(it.progress_json or "{}"), "reject_reason": it.reject_reason,
        "params": json.loads(it.params_json or "{}"),
    }


def plan_dict(db: Session, user_id: int) -> dict:
    plan = active_plan(db, user_id)
    pending = (db.query(PlanVersion).filter_by(user_id=user_id, status="pending")
               .order_by(PlanVersion.version.desc()).first())
    out = {"active": None, "pending": None}
    if plan:
        out["active"] = {"id": plan.id, "version": plan.version, "as_of": plan.as_of.isoformat(),
                         "budget_at_plan": round(plan.budget_at_plan), "trigger": plan.trigger,
                         "baseline": json.loads(plan.baseline_json or "{}"),
                         "items": [item_dict(i) for i in plan.items]}
    if pending:
        items = db.query(ActionItem).filter_by(plan_version_id=pending.id).order_by(ActionItem.priority).all()
        out["pending"] = {"id": pending.id, "version": pending.version, "trigger": pending.trigger,
                          "comparison": json.loads(pending.comparison_json or "{}"),
                          "items": [item_dict(i) for i in items]}
    return out


def respond_item(db: Session, user_id: int, item_id: int, action: str, reason: Optional[str] = None,
                 today: Optional[date] = None) -> dict:
    today = today or date.today()
    it = db.get(ActionItem, item_id)
    if it is None or it.user_id != user_id:
        raise LookupError("항목을 찾을 수 없습니다.")
    if action == "accept":
        if it.status != "PROPOSED":
            raise ValueError(f"제안 상태에서만 수락할 수 있습니다(현재 {it.status}).")
        ctx = build_context(db, user_id, exclude_adopted=False)
        it.status, it.accepted_on = "ACCEPTED", today
        it.accepted_as_of = ctx.window[-1] if ctx.window else None
        progress = {"state": "waiting", "note": "수락 이후 완결된 달의 데이터로 이행 여부를 확인합니다." if it.tracked_by == "auto"
                    else "직접 완료를 체크해 주세요."}
        it.progress_json = json.dumps(progress, ensure_ascii=False)
    elif action == "reject":
        if it.status not in ("PROPOSED", "ACCEPTED"):
            raise ValueError(f"거절할 수 없는 상태입니다({it.status}).")
        it.status, it.reject_reason = "REJECTED", (reason or "사유 없음")[:200]
    elif action == "done":
        if it.status not in ("ACCEPTED", "PROPOSED"):
            raise ValueError(f"완료로 바꿀 수 없는 상태입니다({it.status}).")
        it.status = "DONE"
        it.progress_json = json.dumps({"state": "done", "by": "user"}, ensure_ascii=False)
    else:
        raise ValueError("action은 accept / reject / done 중 하나여야 합니다.")
    db.commit()
    return item_dict(it)


# ===========================================================================
# 이행 추적 · 경로 이탈 감지
# ===========================================================================
def track(db: Session, user_id: int, today: Optional[date] = None) -> List[dict]:
    """수락한 항목의 이행 여부를 마이데이터(분류 결과)로 자동 판정하고, 오래된 제안은 만료한다."""
    today = today or date.today()
    plan = active_plan(db, user_id)
    if plan is None:
        return []
    ctx = build_context(db, user_id, exclude_adopted=False)
    last = ctx.window[-1] if ctx.window else None
    changes = []
    for it in plan.items:
        if it.status == "PROPOSED" and it.proposed_on and (today - it.proposed_on).days > params.G_PROPOSAL_EXPIRE_DAYS:
            it.status = "EXPIRED"
            changes.append({"id": it.id, "key": it.item_key, "status": "EXPIRED"})
            continue
        if it.status != "ACCEPTED" or it.tracked_by != "auto" or last is None:
            continue
        p = json.loads(it.params_json or "{}")
        if not it.accepted_as_of or last <= it.accepted_as_of:
            continue                                   # 수락 이후 완결된 달이 아직 없다
        if p.get("kind") == "category_cut":
            actual = ctx.category_monthly.get(p["category"], {}).get(last, 0.0)
            saved = p["baseline_avg"] - actual
            ratio = saved / it.monthly_saving if it.monthly_saving else 0.0
            prog = {"state": "checked", "month": last, "baseline_avg": p["baseline_avg"],
                    "actual": round(actual), "saved": round(saved), "ratio": round(ratio, 2)}
            done = ratio >= params.G_DONE_RATIO
        elif p.get("kind") == "subscription":
            present = ctx.fixed_by_merchant.get(p["merchant"], {}).get(last, 0.0) > 0
            prog = {"state": "checked", "month": last, "still_charged": present, "ratio": 0.0 if present else 1.0}
            done = not present
        else:
            continue
        it.progress_json = json.dumps(prog, ensure_ascii=False)
        if done:
            it.status = "DONE"
            changes.append({"id": it.id, "key": it.item_key, "status": "DONE", "progress": prog})
    db.commit()
    return changes


def deviation(db: Session, user_id: int, ctx: Optional[PlannerContext] = None) -> Optional[dict]:
    """계획 대비 이탈 판정(E-02): 월 여유 자금 ±10% 또는 달성 예상 시기 ±2개월 또는 목표 변경"""
    plan = active_plan(db, user_id)
    if plan is None:
        return None
    ctx = ctx or build_context(db, user_id, exclude_adopted=False)
    base = json.loads(plan.baseline_json or "{}")
    realized = sum(i.monthly_saving for i in plan.items if i.status == "DONE" and i.monthly_saving > 0)
    expected = plan.budget_at_plan + realized
    reasons = []

    sig_now = sorted([g.name, round(g.target_amount), g.target_date.isoformat() if g.target_date else None]
                     for g in ctx.path_input.goals)
    if sig_now != base.get("goals_sig"):
        reasons.append(("goal_change", "goal", "목표가 바뀌었어요"))

    denom = max(abs(expected), 1.0)
    delta = ctx.budget - expected
    if abs(delta) / denom >= params.DEVIATION_BUDGET_RATIO and abs(delta) >= 10_000:
        direction = "down" if delta < 0 else "up"
        reasons.append(("budget_change", direction,
                        f"월 여유 자금이 계획보다 {abs(delta):,.0f}원 {'줄었' if delta < 0 else '늘었'}어요"
                        f"({expected:,.0f}원 → {ctx.budget:,.0f}원)"))

    for g_old in base.get("goals", []):
        g_new = ctx.base.goal(g_old["name"])
        if g_new is None or g_old["completion_date"] is None or g_new.completion_date is None:
            continue
        d_old = date.fromisoformat(g_old["completion_date"])
        diff = (g_new.completion_date.year - d_old.year) * 12 + (g_new.completion_date.month - d_old.month)
        if abs(diff) >= params.DEVIATION_DELAY_MONTHS:
            reasons.append(("delay", "late" if diff > 0 else "early",
                            f"'{g_old['name']}' 달성 예상이 {abs(diff)}개월 {'늦어졌' if diff > 0 else '빨라졌'}어요"))
            break
    if not reasons:
        return None
    trig, detail, msg = reasons[0]
    return {"trigger": trig, "reason_key": f"{trig}:{detail}", "message": msg,
            "all": [r[2] for r in reasons], "budget_expected": round(expected), "budget_now": round(ctx.budget)}


# ===========================================================================
# 재설계 (제안 → 승인 후 적용)
# ===========================================================================
def propose_replan(db: Session, user_id: int, today: Optional[date] = None, force: bool = False) -> Optional[dict]:
    today = today or date.today()
    plan = active_plan(db, user_id)
    if plan is None:
        return None
    if db.query(PlanVersion).filter_by(user_id=user_id, status="pending").count() > 0:
        return None                                   # 승인 대기 중인 제안이 있으면 새로 만들지 않는다
    ctx = build_context(db, user_id, exclude_adopted=True)
    dev = deviation(db, user_id, ctx)
    if dev is None:
        return None
    cutoff = today - timedelta(days=params.REPLAN_COOLDOWN_DAYS)
    rejected = db.query(PlanVersion).filter(
        PlanVersion.user_id == user_id, PlanVersion.status == "rejected",
        PlanVersion.reason_key == dev["reason_key"], PlanVersion.decided_on >= cutoff).count()
    if rejected and not force:
        return None                                   # 같은 사유로 거절한 뒤 30일 동안은 재제안하지 않는다

    cands = cand_engine.generate(ctx.cand_ctx)
    chosen = [c for c in cands if c["mandatory"]] + [c for c in cands if not c["mandatory"]][:params.G_TOP_ACTIONS]
    new_base = _baseline_summary(ctx)
    old_base = json.loads(plan.baseline_json or "{}")
    comparison = {
        "trigger": dev["trigger"], "message": dev["message"],
        "budget_before": old_base.get("budget"), "budget_after": new_base["budget"],
        "goals": [{"name": o["name"], "before": o["completion_date"],
                   "after": next((n["completion_date"] for n in new_base["goals"] if n["name"] == o["name"]), None)}
                  for o in old_base.get("goals", [])],
        "carried_over": [i.title for i in plan.items if i.status in ("ACCEPTED", "DONE")],
    }
    nxt = PlanVersion(user_id=user_id, version=plan.version + 1, status="pending", trigger=dev["trigger"],
                      reason_key=dev["reason_key"], as_of=ctx.as_of, budget_at_plan=ctx.budget,
                      baseline_json=json.dumps(new_base, ensure_ascii=False),
                      comparison_json=json.dumps(comparison, ensure_ascii=False))
    db.add(nxt)
    db.flush()
    for rank, c in enumerate(chosen, 1):
        it = ActionItem(user_id=user_id, plan_version_id=nxt.id, item_key=c["key"], proposed_on=today)
        _fill_item(it, c, rank)
        db.add(it)
    db.commit()
    notify(db, user_id, "replan_proposal", "high", "계획 재설계를 제안해요",
           f"{dev['message']}. 변경 전·후를 비교하고 승인하면 새 계획이 적용돼요.",
           f"replan:{dev['reason_key']}", nxt.id, today)
    return plan_dict(db, user_id)["pending"]


def decide_plan(db: Session, user_id: int, version_id: int, approve: bool, note: Optional[str] = None,
                today: Optional[date] = None) -> dict:
    """재설계 제안을 사용자가 승인하거나 거절한다. 승인 전에는 기존 계획이 유지된다."""
    today = today or date.today()
    pv = db.get(PlanVersion, version_id)
    if pv is None or pv.user_id != user_id:
        raise LookupError("계획 버전을 찾을 수 없습니다.")
    if pv.status != "pending":
        raise ValueError(f"승인 대기 상태가 아닙니다(현재 {pv.status}).")
    pv.decided_on, pv.decision_note = today, (note or "")[:200]
    if not approve:
        pv.status = "rejected"
        db.commit()
        return {"status": "rejected", "version": pv.version}

    old = active_plan(db, user_id)
    if old is not None:
        old.status = "superseded"
        for it in old.items:                          # 수락·완료한 항목은 새 버전으로 이어 간다
            if it.status in ("ACCEPTED", "DONE"):
                carried = ActionItem(
                    user_id=user_id, plan_version_id=pv.id, item_key=it.item_key, action_type=it.action_type,
                    title=it.title, description=it.description, monthly_saving=it.monthly_saving,
                    params_json=it.params_json, path_effect_json=it.path_effect_json, rationale=it.rationale,
                    priority=it.priority, mandatory=it.mandatory, status=it.status, tracked_by=it.tracked_by,
                    proposed_on=it.proposed_on, accepted_on=it.accepted_on, accepted_as_of=it.accepted_as_of,
                    progress_json=it.progress_json)
                db.add(carried)
            elif it.status == "PROPOSED":
                it.status = "EXPIRED"
    # 새 버전에서 이미 이어 온 항목과 겹치는 신규 제안은 제거
    carried_keys = {i.item_key for i in db.query(ActionItem).filter_by(plan_version_id=pv.id, ) if i.status in ("ACCEPTED", "DONE")}
    for it in db.query(ActionItem).filter_by(plan_version_id=pv.id):
        if it.status == "PROPOSED" and it.item_key in carried_keys:
            db.delete(it)
    pv.status = "active"
    db.commit()
    return {"status": "active", "version": pv.version}


# ===========================================================================
# 소비 변화 모니터링 (동기화 직후 실행)
# ===========================================================================
def run_monitoring(db: Session, user_id: int, today: Optional[date] = None) -> dict:
    today = today or date.today()
    ctx = build_context(db, user_id, exclude_adopted=False)
    res = mon_engine.detect(ctx.category_monthly, ctx.window, ctx.snapshot.monthly_income_net,
                            ctx.fixed_by_merchant, ctx.income_by_month, ctx.one_off)
    db.query(MonitoringEvent).filter_by(user_id=user_id).delete()
    out = []
    for e in res["events"]:
        delay = _goal_delay(ctx, e)
        grade = e["grade"]
        if e["judgement"] == "structural" and delay is not None and delay >= params.DEVIATION_DELAY_MONTHS:
            grade = "high"
        row = MonitoringEvent(
            user_id=user_id, event_type=e["event_type"], category=e["category"], month=e["month"],
            judgement=e["judgement"], grade=grade, recent=e["recent"], baseline=e["baseline"],
            monthly_impact=e["monthly_impact"], goal_delay_months=delay,
            message=e["message"] + (f" 이 속도면 '{_headline(ctx)}' 달성이 {delay}개월 늦어져요." if delay else ""),
            reason=e["reason"])
        db.add(row)
        out.append(row)
    db.commit()
    for row in out:                                  # 알림: 구조적 변화는 중간 이상, 일시적 변화는 낮음(주간 요약)
        if row.event_type == "category_decrease":
            continue
        notify(db, user_id, "spending_change", row.grade, _event_title(row), row.message,
               f"spend:{row.event_type}:{row.category}:{row.month}", row.id, today)
    return {"status": res["status"], "note": res.get("note"), "events": [event_dict(r) for r in out]}


def _headline(ctx: PlannerContext) -> str:
    for g in sorted(ctx.base.goals, key=lambda g: g.priority):
        if g.status != "done":
            return g.name
    return ""


def _goal_delay(ctx: PlannerContext, e: dict) -> Optional[int]:
    """이 변화가 계속되면 목표 달성이 몇 개월 늦어지는가 = (변화가 없었을 때) 대비 현재 경로의 지연"""
    if e["judgement"] != "structural" or e["monthly_impact"] <= 0:
        return None
    from app.planner.path import with_budget
    if not ctx.base.goals:
        return None
    head = _headline(ctx)
    without = simulate(with_budget(ctx.path_input, e["monthly_impact"]))
    a, b = ctx.base.goal(head), without.goal(head)
    if a is None or b is None or a.completion_k is None or b.completion_k is None:
        return None
    delay = a.completion_k - b.completion_k
    return delay if delay > 0 else None


def _event_title(row: MonitoringEvent) -> str:
    return {"category_increase": f"{row.category} 지출 변화", "new_subscription": "새 정기결제",
            "fixed_increase": "정기결제 금액 상승", "income_change": "수입 변화"}.get(row.event_type, "소비 변화")


def event_dict(r: MonitoringEvent) -> dict:
    return {"id": r.id, "event_type": r.event_type, "category": r.category, "month": r.month,
            "judgement": r.judgement, "grade": r.grade, "recent": round(r.recent), "baseline": round(r.baseline),
            "monthly_impact": round(r.monthly_impact), "goal_delay_months": r.goal_delay_months,
            "message": r.message, "reason": r.reason}


def list_events(db: Session, user_id: int) -> List[dict]:
    rows = db.query(MonitoringEvent).filter_by(user_id=user_id).all()
    order = {"high": 0, "medium": 1, "low": 2}
    return [event_dict(r) for r in sorted(rows, key=lambda r: (order[r.grade], r.category))]


def mark_one_off(db: Session, user_id: int, category: str, month: str) -> dict:
    """'일회성'으로 지정 — 평균 산출과 변화 판정에서 제외하고 모니터링을 다시 실행한다."""
    if db.query(OneOffMark).filter_by(user_id=user_id, category=category, month=month).first() is None:
        db.add(OneOffMark(user_id=user_id, category=category, month=month))
        db.commit()
    return run_monitoring(db, user_id)


# ===========================================================================
# 알림 (알림 설계: 등급 · 빈도 제한 · 중복 억제)
# ===========================================================================
def notify(db: Session, user_id: int, kind: str, grade: str, title: str, body: str, dedupe_key: str,
           related_id: Optional[int] = None, today: Optional[date] = None) -> Optional[Notification]:
    today = today or date.today()
    recent = db.query(Notification).filter(
        Notification.user_id == user_id, Notification.dedupe_key == dedupe_key,
        Notification.created_on > today - timedelta(days=params.NOTIFY_DEDUPE_DAYS)).first()
    if recent is not None:
        return None                                   # 같은 이벤트는 7일간 재알림하지 않는다
    if grade == "high":
        immediate_today = db.query(Notification).filter_by(
            user_id=user_id, delivery="immediate", created_on=today).count()
        delivery = "immediate" if immediate_today < params.NOTIFY_IMMEDIATE_PER_DAY else "daily"
    elif grade == "medium":
        delivery = "daily"
    else:
        delivery = "weekly"
    n = Notification(user_id=user_id, kind=kind, grade=grade, delivery=delivery, title=title, body=body,
                     dedupe_key=dedupe_key, related_id=related_id, created_on=today)
    db.add(n)
    db.commit()
    return n


def list_notifications(db: Session, user_id: int, unread_only: bool = False) -> List[dict]:
    q = db.query(Notification).filter_by(user_id=user_id)
    if unread_only:
        q = q.filter_by(status="unread")
    rows = q.order_by(Notification.id.desc()).all()
    return [{"id": n.id, "kind": n.kind, "grade": n.grade, "delivery": n.delivery, "title": n.title,
             "body": n.body, "status": n.status, "created_on": n.created_on.isoformat(),
             "related_id": n.related_id} for n in rows]


def mark_read(db: Session, user_id: int, notification_id: int) -> bool:
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user_id:
        return False
    n.status = "read"
    db.commit()
    return True


# ===========================================================================
# 동기화 직후 훅
# ===========================================================================
def after_sync(db: Session, user_id: int, today: Optional[date] = None) -> dict:
    """마이데이터 동기화 직후: 소비 변화 감지 → 이행 추적 → 경로 이탈 시 재설계 제안"""
    mon = run_monitoring(db, user_id, today)
    tracked = track(db, user_id, today)
    pending = propose_replan(db, user_id, today)
    return {"monitoring_events": len(mon["events"]), "tracked_changes": len(tracked),
            "replan_proposed": pending is not None}
