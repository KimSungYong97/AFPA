"""피드백 루프 — 거절에서 배우고(거절 학습), 실천한 결과를 되돌려 알린다(사후 보고)

거절 학습: 사용자가 제안을 거절한 이유를 코드가 규칙으로 바꿔 다음 제안에 반영한다. LLM은 쓰지 않는다.
  이미 하고 있어요 / 꼭 필요한 지출이에요 → 같은 제안을 1년 동안 하지 않는다
  그냥 하기 싫어요                        → 90일 동안 하지 않는다
  금액이 부담돼요                         → 30일 동안 하지 않고, 같은 카테고리 절감 제안은 규모를 절반으로 줄여 다시 낸다
  나중에 할게요                           → 30일 동안 하지 않는다
  필수 항목(비상금·적자 해소)은 거절해도 학습하지 않는다(안전을 위해 계속 보여 준다).
사후 보고: 수락한 제안의 실제 결과(마이데이터로 확인한 절감액)를 모아, "이 덕분에 목표가 N개월 빨라졌다"를 기준 경로와 비교해 계산한다.
"""
import json
from datetime import date, timedelta
from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.models.entities import ActionItem, PlanVersion, PlannerPreference
from app.pipeline import params

REASONS = {                       # 코드 → (화면 문구, 다시 제안하지 않는 일수, 규모 축소 여부)
    "already": ("이미 하고 있어요", params.G_REJECT_LONG_DAYS, False),
    "needed": ("꼭 필요한 지출이에요", params.G_REJECT_LONG_DAYS, False),
    "burden": ("금액이 부담돼요", params.G_REJECT_SHORT_DAYS, True),
    "later": ("나중에 할게요", params.G_REJECT_SHORT_DAYS, False),
    "other": ("그냥 하기 싫어요", params.G_REJECT_MID_DAYS, False),
}
LABEL_TO_CODE = {v[0]: k for k, v in REASONS.items()}


def _category_of(key: str) -> Optional[str]:
    return key.split(":", 1)[1] if key.startswith(("cut:", "restore:")) else None


# ---------------------------------------------------------------------------
# 거절 학습
# ---------------------------------------------------------------------------
def record_rejection(db: Session, user_id: int, item_key: str, mandatory: bool, reason_code: Optional[str],
                     reason_text: str, today: Optional[date] = None) -> Optional[dict]:
    """거절을 선호로 바꿔 저장한다. 필수 항목이거나 사유를 알 수 없으면 아무것도 하지 않는다."""
    today = today or date.today()
    if mandatory:
        return None
    code = reason_code if reason_code in REASONS else LABEL_TO_CODE.get(reason_text or "", "later")
    _, days, shrink = REASONS[code]
    pref = db.query(PlannerPreference).filter_by(user_id=user_id, kind="exclude", target=item_key).first()
    until = today + timedelta(days=days)
    if pref is None:
        pref = PlannerPreference(user_id=user_id, kind="exclude", target=item_key, created_on=today)
        db.add(pref)
    pref.until, pref.reason_code, pref.reason_text = until, code, (reason_text or REASONS[code][0])[:200]
    cat = _category_of(item_key)
    if shrink and cat:
        sc = db.query(PlannerPreference).filter_by(user_id=user_id, kind="cut_scale", target=cat).first()
        if sc is None:
            sc = PlannerPreference(user_id=user_id, kind="cut_scale", target=cat, value=1.0, created_on=today,
                                   reason_code=code, reason_text="금액이 부담돼서 줄여 달라고 했어요")
            db.add(sc)
        sc.value = max(sc.value * params.G_BURDEN_SCALE, params.G_MIN_CUT_SCALE)
    db.commit()
    return {"code": code, "until": until.isoformat(), "shrink": bool(shrink and cat)}


def learned(db: Session, user_id: int, today: Optional[date] = None) -> dict:
    """지금 유효한 선호: {"exclude": {후보 키}, "cut_scale": {카테고리: 배율}}"""
    today = today or date.today()
    exclude: Set[str] = set()
    scale: Dict[str, float] = {}
    for p in db.query(PlannerPreference).filter_by(user_id=user_id):
        if p.kind == "exclude" and (p.until is None or p.until >= today):
            exclude.add(p.target)
        elif p.kind == "cut_scale":
            scale[p.target] = p.value
    return {"exclude": exclude, "cut_scale": scale}


def list_preferences(db: Session, user_id: int, today: Optional[date] = None) -> List[dict]:
    today = today or date.today()
    out = []
    for p in db.query(PlannerPreference).filter_by(user_id=user_id).order_by(PlannerPreference.id.desc()):
        if p.kind == "exclude" and p.until is not None and p.until < today:
            continue                                   # 기간이 지난 것은 보여 주지 않는다
        out.append({"id": p.id, "kind": p.kind, "target": p.target, "value": p.value,
                    "until": p.until.isoformat() if p.until else None, "reason": p.reason_text,
                    "created_on": p.created_on.isoformat()})
    return out


def delete_preference(db: Session, user_id: int, pref_id: int) -> bool:
    p = db.get(PlannerPreference, pref_id)
    if p is None or p.user_id != user_id:
        return False
    db.delete(p)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# 사후 보고
# ---------------------------------------------------------------------------
def _won(v: float) -> str:
    return f"{round(v):,}원"


def outcome_report(db: Session, user_id: int) -> dict:
    """수락·완료한 제안이 실제로 얼마나 지켜졌는지와, 그 덕분에 목표가 얼마나 빨라졌는지를 코드로 계산한다."""
    from app.planner.path import compare, simulate, with_budget
    from app.services import planner_service as ps

    plan = ps.active_plan(db, user_id)
    if plan is None:
        return {"has_plan": False, "items": [], "realized_monthly": 0, "expected_monthly": 0, "goal_effect": None,
                "waiting_count": 0, "headline": "아직 실천한 제안이 없어요."}
    rows, realized, expected, waiting = [], 0.0, 0.0, 0
    for it in plan.items:
        if it.status not in ("ACCEPTED", "DONE") or it.mandatory:
            continue
        prog = json.loads(it.progress_json or "{}")
        exp = abs(it.monthly_saving)
        if prog.get("state") == "checked":
            if "saved" in prog:
                actual = max(float(prog["saved"]), 0.0)
            else:                                        # 구독: 해지됐으면 월 결제액만큼 아낀 것
                actual = 0.0 if prog.get("still_charged") else exp
            ratio = actual / exp if exp else 0.0
            state = "achieved" if ratio >= params.G_DONE_RATIO else "partial" if actual > 0 else "not_yet"
            realized += min(actual, exp * 1.5)
            expected += exp
            rows.append({"key": it.item_key, "title": it.title, "status": it.status, "state": state,
                         "expected": round(exp), "actual": round(actual), "ratio": round(ratio, 2), "month": prog.get("month")})
        elif prog.get("state") == "done":                # 사용자가 직접 완료 체크: 금액은 확인할 수 없다
            rows.append({"key": it.item_key, "title": it.title, "status": it.status, "state": "self_reported",
                         "expected": round(exp), "actual": None, "ratio": None, "month": None})
        else:
            waiting += 1
            rows.append({"key": it.item_key, "title": it.title, "status": it.status, "state": "waiting",
                         "expected": round(exp), "actual": None, "ratio": None, "month": None})

    effect = None
    if realized > 0:
        ctx = ps.build_context(db, user_id, exclude_adopted=False)
        without = simulate(with_budget(ctx.path_input, -realized))     # 이 행동들이 없었다면
        for cmp_ in compare(without, ctx.base):                        # 지금(행동 반영) 경로와 비교
            g = ctx.base.goal(cmp_["goal"])
            if g is not None and g.status != "done":
                effect = {"goal": cmp_["goal"], "months_saved": cmp_["months_saved"], "makes_reachable": cmp_["makes_reachable"]}
                break
    n_ok = sum(1 for r in rows if r["state"] in ("achieved", "partial"))
    if realized > 0:
        headline = f"실천한 {n_ok}가지로 지난달 {_won(realized)}을 아꼈어요."
        if effect and effect["makes_reachable"]:
            headline += f" 덕분에 '{effect['goal']}'을(를) 기한 내에 이룰 수 있게 됐어요."
        elif effect and effect["months_saved"]:
            headline += f" 덕분에 '{effect['goal']}' 달성이 {effect['months_saved']}개월 앞당겨졌어요."
    elif waiting:
        headline = "수락한 제안의 결과는 다음 달 데이터가 들어오면 확인해 드릴게요."
    else:
        headline = "아직 확인된 절감 결과가 없어요."
    return {"has_plan": True, "items": rows, "realized_monthly": round(realized), "expected_monthly": round(expected),
            "goal_effect": effect, "waiting_count": waiting, "headline": headline}
