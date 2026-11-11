"""변화 감시 에이전트 — 사용자의 금융 프로필 변화를 지켜보고, 알리고, 계획 변경이 필요한지 알려 준다

역할 분담 (「LLM 사용 원칙」)
  코드 : 스냅샷 비교로 변화를 찾고, 계획 이탈(경로 이탈)을 판정하고, 모든 숫자를 계산한다.
         '계획 변경이 필요한가'의 최종 결정, 알림 발송, 재설계 제안 생성도 코드가 한다.
  LLM  : 무엇을 조사할지 스스로 정해 도구를 호출하고(관찰 → 조사), 변화의 의미를 해석하며,
         사용자에게 되물을 질문과 다음 행동을 정리한다. 출력의 수치가 도구 결과에 없으면 폐기하고 규칙 문장으로 대체한다.

한 번의 실행(run) = 관찰(코드) → 조사(LLM이 도구 호출) → 판단 → 행동(알림·재설계 제안, 코드) → 기록
상태를 바꾸는 행동은 '알림'과 '재설계 제안(승인 대기)'까지다. 실제 금융 거래·계획 적용은 하지 않는다.
"""
import json
import logging
import re
import threading
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm_client import get_llm_client, llm_enabled
from app.models.entities import AgentRun, FinancialSnapshot, PlanVersion
from app.pipeline import params
from app.planner import candidates as cand_engine
from app.services import planner_service as ps
from app.services.briefing_service import validate_numbers

logger = logging.getLogger(__name__)

# (필드, 표시 이름, 단위, 방식, 임계값)  방식: rel=비율, rel_abs=비율+1만 원 이상, abs=절대 변화량
FIELDS = [
    ("monthly_income_net", "월 소득", "won", "rel", params.A_INCOME_CHANGE_RATIO),
    ("net_cash_flow", "월 여유 자금", "won", "rel_abs", params.A_BUDGET_CHANGE_RATIO),
    ("net_worth", "순자산", "won", "rel", params.A_NETWORTH_CHANGE_RATIO),
    ("health_score", "재무 건강 점수", "score", "abs", params.A_SCORE_CHANGE_POINTS),
    ("dsr_ratio", "빚 상환 부담(DSR)", "pct", "abs", params.A_RATIO_CHANGE_POINTS),
    ("emergency_fund_ratio", "비상금 충족률", "pct", "abs", params.A_RATIO_CHANGE_POINTS),
]
TOOL_LABEL = {"get_profile_changes": "프로필 변화 조회", "get_spending_events": "소비 변화 조회",
              "get_plan_status": "계획 이탈 여부 확인", "get_recommended_actions": "대응 행동 후보 조회",
              "what_if_save_more": "'더 저축하면?' 계산"}


# ===========================================================================
# 표현 도우미 — LLM에게 주는 숫자는 모두 사람이 읽는 문자열로 미리 만들어 둔다 (수치 검증의 근거가 된다)
# ===========================================================================
def _won(v: float) -> str:
    return f"{round(v):,}원"


def _ym(d: Optional[date]) -> str:
    return "달성 어려움" if d is None else f"{d.year}년 {d.month}월"


def _fmt(v: Optional[float], unit: str) -> str:
    if v is None:
        return "없음"
    if unit == "won":
        return _won(v)
    if unit == "pct":
        return f"{v:.0f}%"
    return f"{v:.0f}점"


# ===========================================================================
# 관찰 (코드): 이전에 본 스냅샷과 지금 스냅샷을 비교한다
# ===========================================================================
def compare_snapshots(prev: FinancialSnapshot, cur: FinancialSnapshot) -> List[dict]:
    out: List[dict] = []
    for field, label, unit, mode, threshold in FIELDS:
        a, b = getattr(prev, field), getattr(cur, field)
        if a is None or b is None:
            continue
        diff = b - a
        if mode == "abs":
            sig = abs(diff) >= threshold
        else:
            rel = abs(diff) / max(abs(a), 1.0)
            sig = rel >= threshold and (mode == "rel" or abs(diff) >= 10_000)
        if not sig:
            continue
        up = diff > 0
        if unit == "won":
            ratio = abs(diff) / max(abs(a), 1.0) * 100
            detail = f"{_won(abs(diff))} {'증가' if up else '감소'}, {ratio:.0f}% {'증가' if up else '감소'}"
        elif unit == "pct":
            detail = f"{abs(diff):.0f}%p {'상승' if up else '하락'}"
        else:
            detail = f"{abs(diff):.0f}점 {'상승' if up else '하락'}"
        out.append({"field": field, "item": label, "before": _fmt(a, unit), "after": _fmt(b, unit),
                    "direction": "up" if up else "down", "detail": detail,
                    "text": f"{label}: {_fmt(a, unit)} → {_fmt(b, unit)} ({detail})"})
    for i, c in enumerate(out, 1):
        c["id"] = f"C{i}"
    return out


# ===========================================================================
# 도구 (코드): 모두 조회·계산만 하고 상태를 바꾸지 않는다
# ===========================================================================
class _Ctx:
    def __init__(self, db: Session, user_id: int, today: Optional[date], changes: List[dict], events: List[dict]):
        self.db, self.user_id, self.today = db, user_id, today
        self.changes, self.events = changes, events


def tool_get_profile_changes(c: _Ctx, **_) -> dict:
    """지난번 확인 이후 달라진 금융 프로필 항목(소득·여유 자금·순자산·점수 등)을 조회한다."""
    if not c.changes:
        return {"changes": [], "note": "눈에 띄게 달라진 프로필 항목이 없어요."}
    return {"changes": [{"id": x["id"], "text": x["text"]} for x in c.changes]}


def tool_get_spending_events(c: _Ctx, **_) -> dict:
    """카테고리별 소비 변화 이벤트(구조적/일시적 판정 포함)를 조회한다."""
    if not c.events:
        return {"events": [], "note": "감지된 소비 변화가 없어요."}
    return {"events": [{"id": e["id"], "judgement": "구조적(지속될 변화)" if e["judgement"] == "structural" else "일시적",
                        "text": e["message"]} for e in c.events]}


def tool_get_plan_status(c: _Ctx, **_) -> dict:
    """현재 계획과 지금 상황을 비교한다: 계획 변경이 필요한지(코드 판정), 목표별 달성 예상 시기 변화."""
    plan = ps.active_plan(c.db, c.user_id)
    if plan is None:
        return {"has_plan": False, "plan_change_needed": False, "note": "아직 만들어진 계획이 없어요."}
    ctx = ps.build_context(c.db, c.user_id, exclude_adopted=False)
    dev = ps.deviation(c.db, c.user_id, ctx)
    base = json.loads(plan.baseline_json or "{}")
    goals = []
    for g in base.get("goals", []):
        now = ctx.base.goal(g["name"])
        old = date.fromisoformat(g["completion_date"]) if g.get("completion_date") else None
        new = now.completion_date if now else None
        delay = None
        if old and new:
            delay = (new.year - old.year) * 12 + (new.month - old.month)
        goals.append({"goal": g["name"], "planned": _ym(old), "now": _ym(new),
                      "delay": None if delay is None else (f"{abs(delay)}개월 {'늦어짐' if delay > 0 else '빨라짐'}" if delay else "변화 없음")})
    return {"has_plan": True, "plan_change_needed": dev is not None,
            "reason": dev["message"] if dev else "계획과 큰 차이가 없어요.",
            "budget_in_plan": _won(plan.budget_at_plan), "budget_now": _won(ctx.budget), "goals": goals}


def tool_get_recommended_actions(c: _Ctx, **_) -> dict:
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
        rows.append({"rank": i, "title": x["title"], "monthly": f"월 {_won(abs(x['monthly_saving']))}",
                     "effect": eff, "mandatory": bool(x["mandatory"])})
    return {"actions": rows}


def tool_what_if_save_more(c: _Ctx, monthly_amount: float = 0, **_) -> dict:
    """매달 저축을 monthly_amount원 더(음수면 덜) 하면 각 목표 달성 시기가 어떻게 바뀌는지 계산한다."""
    try:
        amt = float(monthly_amount)
        res = ps.scenarios_view(c.db, c.user_id, [{"kind": "save_delta", "label": f"월 {round(amt):,}원 추가 저축", "delta": amt}])
    except Exception as e:  # noqa: BLE001 - 범위 오류 등을 LLM에 돌려줘 다시 시도하게 한다
        return {"error": str(e)}
    rows = []
    for r in res["scenarios"][0]["effects"]:
        ms = r["months_saved"]
        eff = ("기한 내 달성이 가능해짐" if r["makes_reachable"] else "기한 내 달성이 어려워짐" if r["becomes_unreachable"]
               else f"{abs(ms)}개월 {'앞당겨짐' if ms > 0 else '늦어짐'}" if ms else "변화 없음")
        base_c = date.fromisoformat(r["base_completion"]) if r["base_completion"] else None
        new_c = date.fromisoformat(r["new_completion"]) if r["new_completion"] else None
        rows.append({"goal": r["goal"], "now": _ym(base_c), "after": _ym(new_c), "effect": eff})
    return {"scenario": f"월 {_won(amt)} 추가 저축", "goals": rows}


TOOLS: Dict[str, Tuple[Callable, dict]] = {
    "get_profile_changes": (tool_get_profile_changes, {}),
    "get_spending_events": (tool_get_spending_events, {}),
    "get_plan_status": (tool_get_plan_status, {}),
    "get_recommended_actions": (tool_get_recommended_actions, {}),
    "what_if_save_more": (tool_what_if_save_more, {"monthly_amount": {
        "type": "number", "description": "매달 추가로 저축할 금액(원). 줄이려면 음수."}}),
}
TOOL_SCHEMAS = [{"type": "function", "function": {
    "name": n, "description": fn.__doc__,
    "parameters": {"type": "object", "properties": props, "required": list(props)}}} for n, (fn, props) in TOOLS.items()]


def _exec(c: _Ctx, name: str, args: dict) -> str:
    entry = TOOLS.get(name)
    if entry is None:
        return json.dumps({"error": f"알 수 없는 도구: {name}"}, ensure_ascii=False)
    try:
        return json.dumps(entry[0](c, **args), ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ===========================================================================
# 조사·판단 (LLM)
# ===========================================================================
SYSTEM_PROMPT = """당신은 사용자의 금융 프로필을 지켜보는 '변화 감시 agent'입니다.
지난번 확인 이후 새 데이터가 들어왔습니다. 도구로 사실을 조사한 뒤 (1) 무엇이 바뀌었는지 (2) 그것이 사용자의 목표에 어떤 의미인지
(3) 계획을 바꿔야 하는지를 판단해 사용자에게 알리세요.

진행 방법
1. 먼저 get_profile_changes, get_spending_events, get_plan_status를 호출해 변화와 계획 상태를 확인합니다.
2. 계획 변경이 필요하거나 변화가 크면 get_recommended_actions나 what_if_save_more로 대응 방안의 효과를 확인합니다.
3. 조사가 끝나면 최종 응답을 JSON으로만 출력합니다.

규칙
- 숫자는 도구 결과에 적힌 그대로만 씁니다. 계산하거나 반올림하거나 새 숫자를 만들지 않습니다.
- 도구가 알려 준 사실만 말합니다. 원인을 단정하지 말고, 모르면 questions로 사용자에게 묻습니다.
- 투자 권유·수익 보장 표현은 쓰지 않습니다. 모든 문장은 해요체(~어요, ~예요)로 짧게 씁니다. '~습니다' 체는 쓰지 않습니다.
- questions는 사용자에게 직접 묻는 질문 문장('~인가요?', '~이어질 것 같나요?')으로 씁니다. 사용자의 입장에서 쓰지 않습니다.
- plan_change_needed는 get_plan_status의 plan_change_needed를 참고해 판단합니다(최종 결정은 시스템이 합니다).

최종 응답 형식:
{"headline": "한 줄 요약", "findings": [{"ref": "C1", "meaning": "그 변화의 의미 1~2문장"}],
 "plan_change_needed": true, "plan_change_reason": "계획 변경이 필요한(또는 불필요한) 이유 1~2문장",
 "next_step": "사용자가 지금 하면 좋은 일 한 문장", "questions": ["사용자에게 확인하고 싶은 것(최대 2개, 없으면 빈 배열)"]}
findings의 ref는 도구가 준 id(C1, E1 등)만 씁니다."""


def _parse_json(content: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", content or "", flags=re.S).strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        text = text[4:] if text.startswith("json") else text
    if "{" not in text:
        raise ValueError("JSON 응답이 아닙니다")
    obj, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])      # 뒤에 군더더기 텍스트가 붙어도 첫 JSON만 읽는다
    if not isinstance(obj, dict):
        raise ValueError("JSON 객체가 아닙니다")
    return obj


def _investigate(c: _Ctx, steps: List[dict], facts: List[str]) -> Tuple[dict, str, List[str]]:
    """LLM이 도구를 골라 호출하며 조사한다. 반환: (최종 JSON, 모드, 호출한 도구 이름들)"""
    client = get_llm_client(timeout=240, max_retries=0)
    if client is None:
        raise RuntimeError("LLM이 설정되지 않았습니다 (LLM_BASE_URL 또는 OPENAI_API_KEY)")
    model = get_settings().llm_model
    extra = {"chat_template_kwargs": {"enable_thinking": False}}
    user_msg = "지난번 확인 이후 새 데이터가 들어왔어요. 조사하고 사용자에게 알릴 내용을 정리해 주세요."
    messages: List[dict] = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_msg}]
    used: List[str] = []
    try:
        for rnd in range(params.A_MAX_TOOL_ROUNDS + 1):
            last_round = rnd == params.A_MAX_TOOL_ROUNDS      # 조사 횟수를 다 썼으면 도구 없이 결론만 내게 한다
            if last_round:
                messages.append({"role": "user", "content": "조사는 여기까지 하고, 지금까지 확인한 사실만으로 최종 JSON을 출력하세요."})
            kwargs = {} if last_round else {"tools": TOOL_SCHEMAS}
            resp = client.chat.completions.create(model=model, messages=messages, temperature=0.1,
                                                  max_tokens=900, extra_body=extra, **kwargs)
            msg = resp.choices[0].message
            if msg.tool_calls:
                messages.append(msg.model_dump(exclude_none=True))
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except ValueError:
                        args = {}
                    out = _exec(c, tc.function.name, args)
                    used.append(tc.function.name)
                    facts.append(out)
                    steps.append({"kind": "tool", "title": TOOL_LABEL.get(tc.function.name, tc.function.name),
                                  "detail": ("인자: " + json.dumps(args, ensure_ascii=False) if args else "")})
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
                continue
            return _parse_json(msg.content or ""), "tool_calling", used
        raise RuntimeError("에이전트가 최대 조사 횟수 안에 결론을 내지 못했습니다.")
    except Exception as e:  # noqa: BLE001
        if used or "tool" not in str(e).lower():
            raise
        logger.warning("서버가 tool-calling을 지원하지 않아 사전 조회 방식으로 전환: %s", str(e)[:120])

    # 폴백: 핵심 도구 결과를 코드가 먼저 조회해 프롬프트에 넣는다(prefetched_context)
    names = ["get_profile_changes", "get_spending_events", "get_plan_status", "get_recommended_actions"]
    ctx_data = {}
    for n in names:
        out = _exec(c, n, {})
        facts.append(out)
        ctx_data[n] = json.loads(out)
        steps.append({"kind": "tool", "title": TOOL_LABEL[n], "detail": "(코드가 먼저 조회해 전달)"})
    resp = client.chat.completions.create(
        model=model, temperature=0.1, max_tokens=900, extra_body=extra,
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": user_msg + "\n\n아래는 코드가 미리 조회한 결과입니다.\n"
                   + json.dumps(ctx_data, ensure_ascii=False)}])
    return _parse_json(resp.choices[0].message.content or ""), "prefetched_context", names


def _validate(out: dict, facts_text: str, known_refs: set) -> dict:
    """LLM 출력 검증: 형식 · 근거 id · 수치. 통과한 것만 돌려주고 실패하면 예외."""
    texts = [out.get("headline", ""), out.get("plan_change_reason", ""), out.get("next_step", "")]
    findings = []
    for f in out.get("findings", []):
        if f.get("ref") in known_refs and f.get("meaning"):
            findings.append({"ref": f["ref"], "meaning": str(f["meaning"])})
            texts.append(str(f["meaning"]))
    questions = [str(q) for q in out.get("questions", [])][:2]
    texts += questions
    if not out.get("headline"):
        raise ValueError("headline이 비어 있습니다")
    for t in texts:
        if not validate_numbers(t, facts_text):
            raise ValueError(f"도구 결과에 없는 수치가 포함된 문장을 폐기했습니다: {t[:60]}")
    return {"headline": str(out["headline"]), "findings": findings,
            "plan_change_reason": str(out.get("plan_change_reason", "")),
            "llm_plan_change_opinion": bool(out.get("plan_change_needed")),
            "next_step": str(out.get("next_step", "")), "questions": questions}


# ===========================================================================
# 규칙 기반 대체 문장 (LLM이 꺼져 있거나 실패·검증 탈락 시)
# ===========================================================================
def _rule_report(changes: List[dict], events: List[dict], status: dict) -> dict:
    names = ", ".join(c["item"] for c in changes[:3])
    headline = (f"지난번 확인 이후 {len(changes)}가지 프로필 변화가 있어요: {names}." if changes
                else "눈에 띄는 프로필 변화는 없지만 소비 변화가 감지됐어요.")
    findings = [{"ref": c["id"], "meaning": "이 변화가 목표 달성에 영향을 줄 수 있어요."} for c in changes]
    findings += [{"ref": e["id"], "meaning": "구조적 변화라 계속될 수 있어요." if e["judgement"] == "structural"
                  else "이번 달에만 나타난 변화예요."} for e in events]
    questions = [f"{e['category']} 지출 증가는 이번 한 번뿐인가요, 앞으로도 이어질 것 같나요?"
                 for e in events if e["judgement"] == "temporary" and e["event_type"] == "category_increase"][:2]
    return {"headline": headline, "findings": findings,
            "plan_change_reason": status.get("reason", ""), "llm_plan_change_opinion": None,
            "next_step": ("제안된 새 계획을 비교해 보고 승인 여부를 정해 주세요." if status.get("plan_change_needed")
                          else "지금 계획을 그대로 유지해도 괜찮아요."),
            "questions": questions}


# ===========================================================================
# 실행
# ===========================================================================
def last_run(db: Session, user_id: int) -> Optional[AgentRun]:
    return db.query(AgentRun).filter_by(user_id=user_id).order_by(AgentRun.id.desc()).first()


def run_dict(r: AgentRun) -> dict:
    body = json.loads(r.result_json or "{}")
    return {"id": r.id, "created_at": r.created_at.isoformat(timespec="seconds"), "status": r.status,
            "severity": r.severity, "generated_by": r.generated_by, "llm_mode": r.llm_mode,
            "fallback_reason": r.fallback_reason, "plan_change_needed": r.plan_change_needed,
            "replan_version_id": r.replan_version_id, **body}


def history(db: Session, user_id: int, limit: int = 10) -> List[dict]:
    rows = db.query(AgentRun).filter_by(user_id=user_id).order_by(AgentRun.id.desc()).limit(limit).all()
    return [run_dict(r) for r in rows]


def _event_key(e: dict) -> str:
    return f"{e['event_type']}:{e['category']}:{e['month']}"


def _reported_event_keys(r: Optional[AgentRun]) -> set:
    """이전 실행에서 이미 본 소비 변화 — 같은 변화를 동기화할 때마다 다시 알리지 않기 위해 쓴다."""
    if r is None:
        return set()
    body = json.loads(r.result_json or "{}")
    return set(body.get("known_events", [])) | {_event_key(e) for e in body.get("events", [])}


def _save(db: Session, user_id: int, snap_id: int, status: str, **kw) -> AgentRun:
    body = kw.pop("body", {})
    row = AgentRun(user_id=user_id, snapshot_id=snap_id, status=status, result_json=json.dumps(body, ensure_ascii=False), **kw)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def ensure_baseline(db: Session, user_id: int) -> Optional[AgentRun]:
    """에이전트가 아직 본 적이 없으면, 지금 상태를 '기준'으로 기록한다(이후 변화는 이 기준과 비교)."""
    snap = (db.query(FinancialSnapshot).filter_by(user_id=user_id)
            .order_by(FinancialSnapshot.calculated_at.desc(), FinancialSnapshot.id.desc()).first())
    if snap is None:
        return None
    if last_run(db, user_id) is not None:
        return None
    return _save(db, user_id, snap.id, "baseline", body={
        "headline": "지금 상태를 기준으로 기록했어요. 앞으로 달라지는 점을 알려 드릴게요.",
        "known_events": [_event_key(e) for e in ps.list_events(db, user_id)],
        "steps": [{"kind": "observe", "title": "기준 저장", "detail": f"{snap.as_of} 기준 프로필을 기억해 뒀어요."}]})


def run(db: Session, user_id: int, use_llm: bool = True, today: Optional[date] = None) -> dict:
    """에이전트 1회 실행. 새 데이터가 없으면 아무것도 하지 않는다."""
    snap = (db.query(FinancialSnapshot).filter_by(user_id=user_id)
            .order_by(FinancialSnapshot.calculated_at.desc(), FinancialSnapshot.id.desc()).first())
    if snap is None:
        raise LookupError("프로필이 없습니다. 먼저 마이데이터를 동기화하세요.")
    prev_run = last_run(db, user_id)
    if prev_run is None:
        return run_dict(ensure_baseline(db, user_id))
    if prev_run.snapshot_id == snap.id:
        return {**run_dict(prev_run), "status": "no_new_data",
                "headline": "지난번 확인 이후 새 데이터가 없어요."}
    prev_snap = db.get(FinancialSnapshot, prev_run.snapshot_id)
    steps: List[dict] = []

    # --- 1. 관찰 (코드) -----------------------------------------------------
    changes = compare_snapshots(prev_snap, snap)
    mon = ps.run_monitoring(db, user_id, today)
    seen = _reported_event_keys(prev_run)             # 지난번까지 이미 본 소비 변화는 다시 알리지 않는다
    known = seen | {_event_key(e) for e in mon["events"]}
    events = [{**e, "id": f"E{i}"} for i, e in enumerate(
        [e for e in mon["events"] if e["event_type"] != "category_decrease" and _event_key(e) not in seen], 1)]
    steps.append({"kind": "observe", "title": "변화 감지",
                  "detail": f"지난번 확인과 비교해 프로필 변화 {len(changes)}건 · 소비 변화 {len(events)}건을 찾았어요."})
    c = _Ctx(db, user_id, today, changes, events)
    status = tool_get_plan_status(c)              # 계획 변경 필요 여부는 코드의 판정이 최종이다
    needed = bool(status.get("plan_change_needed"))

    if not changes and not events and not (needed and not prev_run.plan_change_needed):   # 이미 알린 계획 이탈은 반복하지 않는다
        row = _save(db, user_id, snap.id, "no_change", severity="none", generated_by="rule", body={
            "headline": "달라진 점이 없어서 알리지 않았어요.", "steps": steps, "changes": [], "events": [],
            "known_events": sorted(known)})
        return run_dict(row)

    # --- 2. 조사·판단 (LLM → 검증 → 실패 시 규칙) ------------------------------
    report, generated_by, mode, fallback = None, "rule", None, None
    facts: List[str] = [x["text"] for x in changes] + [e["message"] for e in events] + [json.dumps(status, ensure_ascii=False)]
    if use_llm and llm_enabled():
        try:
            raw, mode, _used = _investigate(c, steps, facts)
            report = _validate(raw, "\n".join(facts), {x["id"] for x in changes} | {e["id"] for e in events})
            generated_by = "llm"
            steps.append({"kind": "decide", "title": "해석·판단", "detail": "AI가 변화의 의미를 정리했고, 문장 속 수치를 도구 결과와 대조해 통과했어요."})
        except Exception as e:  # noqa: BLE001 - 어떤 실패든 규칙 문장으로 대체
            fallback, mode, report = f"{type(e).__name__}: {str(e)[:300]}", None, None
            logger.warning("변화 감시 에이전트 LLM 실패, 규칙으로 대체: %s", fallback)
    else:
        fallback = "LLM이 꺼져 있거나 설정되지 않았어요."
    if report is None:
        report = _rule_report(changes, events, status)
        steps.append({"kind": "decide", "title": "규칙으로 정리", "detail": fallback or ""})
    if report["llm_plan_change_opinion"] is not None and report["llm_plan_change_opinion"] != needed:
        steps.append({"kind": "decide", "title": "판단 차이 정정",
                      "detail": f"AI는 '계획 변경 {'필요' if report['llm_plan_change_opinion'] else '불필요'}'로 봤지만, "
                                f"계산 결과(경로 이탈 판정)에 따라 '{'필요' if needed else '불필요'}'로 확정했어요."})

    # --- 3. 행동 (코드): 알림 + 재설계 제안(승인 대기) ----------------------------
    severity = "important" if (needed or any(e["judgement"] == "structural" for e in events)
                               or any(x["field"] == "monthly_income_net" for x in changes)) else "info"
    replan_id = None
    if needed:
        pending = ps.propose_replan(db, user_id, today)
        if pending is not None:
            replan_id = pending["id"]
            steps.append({"kind": "act", "title": "새 계획 제안 만들기",
                          "detail": "코드가 새 계획안을 만들어 승인 대기로 올렸어요. 승인 전에는 기존 계획이 유지돼요."})
        else:
            pv = (db.query(PlanVersion).filter_by(user_id=user_id, status="pending").order_by(PlanVersion.id.desc()).first())
            replan_id = pv.id if pv else None
    ps.notify(db, user_id, "agent_change", "high" if needed else "medium", report["headline"][:100],
              (report["plan_change_reason"] + " " + report["next_step"]).strip() or report["headline"],
              f"agent:{snap.id}", None, today)
    steps.append({"kind": "act", "title": "알림 보내기", "detail": "알림 센터에 변화 내용을 남겼어요."})

    body = {"headline": report["headline"], "findings": [
                {**f, **next((x for x in changes + events if x["id"] == f["ref"]), {})} for f in report["findings"]],
            "plan_change": {"needed": needed, "reason": report["plan_change_reason"],
                            "llm_opinion": report["llm_plan_change_opinion"],
                            "goals": status.get("goals", [])},
            "next_step": report["next_step"], "questions": report["questions"],
            "steps": steps, "changes": changes, "events": events, "known_events": sorted(known)}
    row = _save(db, user_id, snap.id, "reported", severity=severity, generated_by=generated_by, llm_mode=mode,
                fallback_reason=fallback, plan_change_needed=needed, replan_version_id=replan_id, body=body)
    return run_dict(row)


# ===========================================================================
# 자동 실행 (동기화 직후) — 같은 사용자에 대해 동시에 두 번 돌지 않게 막는다
# ===========================================================================
_RUNNING: set = set()
_LOCK = threading.Lock()


def is_running(user_id: int) -> bool:
    return user_id in _RUNNING


def run_guarded(db: Session, user_id: int, use_llm: bool = True, today: Optional[date] = None) -> Optional[dict]:
    """실행 중이면 건너뛴다(None). 실행 중에는 is_running()이 True."""
    with _LOCK:
        if user_id in _RUNNING:
            return None
        _RUNNING.add(user_id)
    try:
        return run(db, user_id, use_llm=use_llm, today=today)
    finally:
        with _LOCK:
            _RUNNING.discard(user_id)
