"""관리자 agent 브리핑 — 사용자가 보고받는 단일 창구

브리핑의 내용(후보 순위, 경로, 이벤트, 이행 현황)은 모두 코드가 계산한다.
LLM은 이 수치를 자연스러운 문장으로 풀어 쓰는 설명 문구만 맡고, 출력에 근거 없는 수치가 섞이면 폐기하고
템플릿 문장으로 대체한다(「LLM 사용 원칙」: 출력 수치는 코드 결과와 일치해야 한다).
"""
import re
from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.llm_client import get_llm_client
from app.config import get_settings
from app.pipeline import params
from app.services import planner_service as ps

_NUM = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(\S?)")
_COUNT_UNITS = set("순위개월가지번년일배곳")


def _nums(text: str) -> set:
    return {m.group(1).replace(",", "").rstrip(".") for m in _NUM.finditer(text)}


def validate_numbers(output: str, facts: str, free_below: int = 10) -> bool:
    """LLM 출력의 모든 수치가 입력 사실(facts)에 있는 값인지 확인한다.

    작은 서수·개수(예: "1순위", "2개월")는 허용하지만 %·원 같은 금액·비율 단위가 붙은 수치는 반드시 근거가 있어야 한다.
    """
    allowed = _nums(facts)
    for m in _NUM.finditer(output):
        n, unit = m.group(1).replace(",", "").rstrip("."), m.group(2)
        try:
            v = float(n)
        except ValueError:
            return False
        if v < free_below and v == int(v) and unit in _COUNT_UNITS:
            continue
        if n not in allowed and str(int(v)) not in allowed:
            return False
    return True


def facts_text(b: dict) -> str:
    """LLM에 전달하는 사실 목록. 방향(단축/지연)과 필수 항목의 성격을 코드가 미리 문장으로 확정해 둔다."""
    lines = [f"월 여유 자금 {b['monthly_budget']:,}원" + (" (적자)" if b["monthly_budget"] < 0 else "")]
    hg = b.get("headline_path")
    if hg:
        gap = hg.get("gap_months")
        lines.append(f"주요 목표 '{hg['name']}': 예상 달성 {hg['completion_date'] or '기간 내 달성 불가'}"
                     + (f", 기한 대비 {abs(gap)}개월 {'지연' if gap > 0 else '여유'}" if gap else ""))
    for a in b["actions"][:3]:
        e = a["path_effect"]
        if a["key"] == "deficit":
            lines.append(f"필수 '{a['title']}': 월 적자를 먼저 메워야 하며 아래 절감안이 도움이 됨")
            continue
        if a["mandatory"]:
            ms = e.get("months_saved")
            delay = f", 대신 목표 달성이 {-ms}개월 늦어짐" if ms is not None and ms < 0 else ""
            lines.append(f"필수 '{a['title']}': 월 {abs(a['monthly_saving']):,}원씩 먼저 적립{delay}")
            continue
        ms = e.get("months_saved")
        if e.get("makes_reachable"):
            eff = "목표 달성이 가능해짐"
        elif ms:
            eff = f"목표 달성이 {abs(ms)}개월 {'앞당겨짐' if ms > 0 else '늦어짐'}"
        else:
            eff = f"연 {e.get('annual_saving', 0):,}원 절약"
        lines.append(f"{a['rank']}순위 '{a['title']}': 월 {abs(a['monthly_saving']):,}원, {eff}")
    for ev in b["events"][:2]:
        lines.append(ev["message"])
    return "\n".join(lines)


def template_narrative(b: dict) -> str:
    parts = [f"월 여유 자금은 {b['monthly_budget']:,}원이에요."]
    hg = b.get("headline_path")
    if hg:
        if hg["completion_date"] is None:
            parts.append(f"지금 속도로는 '{hg['name']}'을(를) 기간 내 달성하기 어려워요.")
        else:
            gap = hg.get("gap_months")
            tail = "" if not gap else (f" 기한보다 {gap}개월 늦어요." if gap > 0 else f" 기한보다 {-gap}개월 여유가 있어요.")
            parts.append(f"'{hg['name']}'은(는) {hg['completion_date']}쯤 달성할 것으로 예상돼요.{tail}")
    if b["actions"]:
        a = b["actions"][0]
        e = a["path_effect"]
        if a["mandatory"]:
            parts.append(f"먼저 '{a['title']}'부터 하는 것이 좋아요.")
        elif e.get("months_saved"):
            parts.append(f"가장 효과가 큰 행동은 '{a['title']}'이에요. 달성이 {e['months_saved']}개월 앞당겨져요.")
        else:
            parts.append(f"가장 효과가 큰 행동은 '{a['title']}'이에요(월 {abs(a['monthly_saving']):,}원 절약).")
    if b["pending_replan"]:
        parts.append("계획 재설계 제안이 승인을 기다리고 있어요.")
    return " ".join(parts)


def _llm_narrative(facts: str) -> Optional[str]:
    client = get_llm_client(timeout=30, max_retries=0)
    if client is None:
        return None
    s = get_settings()
    try:
        resp = client.chat.completions.create(
            model=s.llm_model, temperature=0.2, max_tokens=300,
            messages=[
                {"role": "system", "content": (
                    "당신은 금융 관리 agent의 브리핑 작성자다. 아래 '사실'만 사용해 한국어 존댓말(해요체) 2~3문장으로 "
                    "요약한다. 사실에 없는 숫자·상품·종목을 만들지 않고, 수치는 사실에 적힌 그대로 쓴다. "
                    "'필수' 항목은 먼저 해야 할 일로, '늦어짐'은 지연으로 정확히 구분해 표현하고 인사말은 쓰지 않는다. "
                    "투자 권유나 수익 보장 표현은 쓰지 않는다.")},
                {"role": "user", "content": facts},
            ],
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        text = (resp.choices[0].message.content or "").strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        return text or None
    except Exception:
        return None


def compose(db: Session, user_id: int, use_llm: bool = False, today: Optional[date] = None) -> dict:
    ctx = ps.build_context(db, user_id)
    from app.planner import candidates as ce
    cands = ce.generate(ctx.cand_ctx)
    top = [c for c in cands if c["mandatory"]] + [c for c in cands if not c["mandatory"]][:params.G_TOP_ACTIONS]
    actions = [{
        "rank": i, "key": c["key"], "title": c["title"], "action_type": c["action_type"],
        "description": c["description"], "monthly_saving": round(c["monthly_saving"]),
        "mandatory": c["mandatory"], "path_effect": {k: v for k, v in c["effect"].items() if k != "per_goal"},
        "conflicts_with": c["conflicts_with"], "rationale": ps._rationale(c),
    } for i, c in enumerate(top, 1)]

    head = next((g for g in sorted(ctx.base.goals, key=lambda g: g.priority) if g.status != "done"), None)
    plan = ps.plan_dict(db, user_id)
    items = plan["active"]["items"] if plan["active"] else []
    counts = {}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    events = [e for e in ps.list_events(db, user_id)]
    notes = ps.list_notifications(db, user_id, unread_only=True)

    brief = {
        "as_of": ctx.as_of.isoformat(), "monthly_budget": round(ctx.budget),
        "headline_path": ps._goal_path_dict(head) if head else None,
        "goals": [ps._goal_path_dict(g) for g in ctx.base.goals],
        "actions": actions, "events": events,
        "tracking": {"counts": counts, "accepted": [i for i in items if i["status"] == "ACCEPTED"]},
        "pending_replan": plan["pending"], "unread_notifications": len(notes),
        "has_plan": plan["active"] is not None,
    }
    facts = facts_text(brief)
    narrative, source = template_narrative(brief), "template"
    if use_llm:
        text = _llm_narrative(facts)
        if text and validate_numbers(text, facts):
            narrative, source = text, "llm"
        elif text:
            source = "template (LLM 출력에 근거 없는 수치가 있어 폐기)"
    brief["narrative"], brief["narrative_source"] = narrative, source
    return brief
