"""대화 에이전트 — 사용자의 자연어 질문을 도구 호출로 바꾸고, 코드가 계산한 결과로만 답한다

"월 30만 원 더 모으면 언제 되나요?", "쇼핑을 20% 줄이면?", "이번 달 말에 돈이 모자랄까요?" 같은 질문을 처리한다.
- LLM: 질문의 의도를 읽어 어떤 도구를 어떤 인자로 부를지 정하고, 도구 결과를 쉬운 말로 풀어 쓴다.
- 코드: 모든 계산(시나리오·전망)과 인자 범위 검증. 답변 속 수치가 도구 결과·질문에 없으면 답을 버리고
  도구 결과를 그대로 정리한 문장으로 대체한다.
실제 이체·가입·종목 추천은 하지 않으며, 도구가 없는 질문은 못 한다고 말한다.
"""
import json
import logging
import re
from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.agent import tools as T
from app.config import get_settings
from app.llm_client import get_llm_client, llm_enabled
from app.services.briefing_service import validate_numbers

logger = logging.getLogger(__name__)

CHAT_TOOLS = ["get_goal_status", "get_cash_forecast", "get_outcome_report", "get_category_spending", "get_recommended_actions",
              "get_plan_status", "what_if_save_more", "what_if_cut_spending", "what_if_one_time_expense",
              "what_if_goal_shift"]
MAX_ROUNDS = 5
MAX_HISTORY = 6
TOOL_LABEL = {"get_goal_status": "목표 현황 조회", "get_outcome_report": "실천 결과 조회", "get_cash_forecast": "월중 현금 전망 조회",
              "get_category_spending": "카테고리별 지출 조회", "get_recommended_actions": "추천 행동 조회",
              "get_plan_status": "계획 상태 확인", "what_if_save_more": "'더 저축하면?' 계산",
              "what_if_cut_spending": "'지출을 줄이면?' 계산", "what_if_one_time_expense": "'한 번 쓰면?' 계산",
              "what_if_goal_shift": "'목표를 바꾸면?' 계산"}

SYSTEM_PROMPT = """당신은 사용자의 돈 관리를 돕는 금융 agent입니다. 사용자의 질문에 답하려면 도구를 호출해 계산 결과를 얻고, 그 결과만으로 답하세요.

규칙
- 숫자는 도구 결과에 적힌 그대로만 씁니다. 계산하거나 반올림하거나 새 숫자를 만들지 않습니다. 사용자가 말한 숫자는 그대로 써도 됩니다.
- 도구를 먼저 호출하세요. 확인하지 않은 사실을 추측해서 말하지 않습니다.
- 질문에 금액·비율·기간처럼 꼭 필요한 값이 빠져 있으면 도구를 부르지 말고 되물어 보세요.
- 도구로 할 수 없는 질문(특정 종목 추천, 세금 신고, 실제 이체·가입 등)은 못 한다고 솔직히 말하고, 할 수 있는 일을 한 문장으로 안내하세요.
- 투자 권유·수익 보장 표현을 쓰지 않습니다.
- 해요체(~어요, ~예요)로 3~5문장, 핵심부터 답합니다.

할 수 있는 일: 목표 달성 시기 확인, 실천한 제안의 결과 확인, '월 N원 더 저축하면?', '○○ 지출을 N% 줄이면?', '△개월 뒤에 N원을 쓰면?', '목표 기한·금액을 바꾸면?', 이번 달 말 현금 전망, 효과 큰 추천 행동."""

EXAMPLES = ["월 30만 원 더 저축하면 목표가 얼마나 빨라져요?", "쇼핑을 20% 줄이면 어떻게 돼요?",
            "이번 달 말에 돈이 모자랄까요?", "지난번에 제안받은 걸 해봤는데 효과가 있었어요?", "6개월 뒤에 200만 원짜리 여행을 가면 목표에 영향이 있어요?"]


def _render(name: str, result: dict) -> List[str]:
    """도구 결과를 그대로 정리한 문장(LLM 답을 쓸 수 없을 때의 대체 답변)"""
    if "error" in result:
        return [f"- {result['error']}"]
    lines: List[str] = []
    if result.get("scenario"):
        lines.append(f"**{result['scenario']}**")
    for g in result.get("goals", []):
        if "effect" in g:
            lines.append(f"- {g['goal']}: {g['now']} → {g['after']} ({g['effect']})")
        elif "expected" in g:
            lines.append(f"- {g['goal']}: 목표 {g['target']}, 달성 예상 {g['expected']} ({g.get('vs_deadline') or '기한 없음'})")
        elif "planned" in g:
            lines.append(f"- {g['goal']}: 계획 {g['planned']} → 지금 {g['now']} ({g.get('delay') or '비교 불가'})")
    for a in result.get("actions", []):
        lines.append(f"- {a['rank']}순위 {a['title']} · {a['monthly']} · {a['effect']}")
    if name == "get_cash_forecast" and result.get("risk"):
        lines += [f"- 위험도: {result['risk']}", f"- 지금까지 변동지출 {result['spent_so_far']}, 월말 예상 {result['projected_variable']}"
                  f" (평소 {result['usual_variable']}, {result['vs_usual']})",
                  f"- 월중 최저 현금: {result['lowest_cash']}, 월말 예상 잔액: {result['month_end_cash']}"]
        lines += [f"- {x}" for x in result.get("overspent_categories", [])]
    for c in result.get("categories", []) if name == "get_category_spending" else []:
        lines.append(f"- {c['category']}: 월평균 {c['monthly_avg']}")
    if result.get("summary"):
        lines.append(f"- {result['summary']}")
        lines += [f"- {i['title']}: {i['state']} (목표 {i['target']}" + (f", 실제 {i['actual']}" if i.get("actual") else "") + ")"
                  for i in result.get("items", [])]
    if result.get("note"):
        lines.append(f"- {result['note']}")
    return lines


def _fallback_answer(calls: List[dict]) -> str:
    lines: List[str] = []
    for c in calls:
        lines += _render(c["name"], c["result"])
    if not lines:
        return "질문을 이해하지 못했어요. 예: " + " / ".join(f"'{e}'" for e in EXAMPLES[:2])
    return "계산 결과만 정리해서 알려 드릴게요.\n\n" + "\n".join(lines)


def chat(db: Session, user_id: int, message: str, history: Optional[List[dict]] = None,
         today: Optional[date] = None, use_llm: bool = True) -> dict:
    message = (message or "").strip()
    if not message:
        raise ValueError("질문을 입력해 주세요.")
    if len(message) > 500:
        raise ValueError("질문은 500자 이내로 써 주세요.")
    if not (use_llm and llm_enabled()):
        return {"answer": "AI가 연결되어 있지 않아서 질문을 이해할 수 없어요. 대신 '내 목표'의 '만약에?' 화면에서 직접 계산해 볼 수 있어요.",
                "source": "rule", "calls": [], "error": "LLM 미설정", "examples": EXAMPLES}
    client = get_llm_client(timeout=120, max_retries=0)
    s = get_settings()
    c = T.Ctx(db, user_id, today)
    messages: List[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in (history or [])[-MAX_HISTORY:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": str(h["content"])[:800]})
    messages.append({"role": "user", "content": message})
    calls: List[dict] = []
    facts: List[str] = [message] + [str(h.get("content", "")) for h in (history or [])[-MAX_HISTORY:] if h.get("role") == "user"]
    extra = {"chat_template_kwargs": {"enable_thinking": False}}
    try:
        for rnd in range(MAX_ROUNDS + 1):
            last = rnd == MAX_ROUNDS
            if last:
                messages.append({"role": "user", "content": "조사는 여기까지 하고, 확인한 결과만으로 사용자에게 답하세요."})
            resp = client.chat.completions.create(model=s.llm_model, messages=messages, temperature=0.1, max_tokens=700,
                                                  extra_body=extra, **({} if last else {"tools": T.schemas(CHAT_TOOLS)}))
            msg = resp.choices[0].message
            if msg.tool_calls:
                messages.append(msg.model_dump(exclude_none=True))
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except ValueError:
                        args = {}
                    out = T.execute(c, tc.function.name, args, CHAT_TOOLS)
                    facts.append(out)
                    calls.append({"name": tc.function.name, "label": TOOL_LABEL.get(tc.function.name, tc.function.name),
                                  "args": args, "result": json.loads(out)})
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
                continue
            text = re.sub(r"<think>.*?</think>", "", msg.content or "", flags=re.S).strip()
            if not text:
                raise ValueError("빈 답변")
            if validate_numbers(text, "\n".join(facts)):
                return {"answer": text, "source": "llm", "calls": calls, "error": None}
            logger.warning("대화 에이전트 답변 폐기(근거 없는 수치): %s", text[:80])
            return {"answer": _fallback_answer(calls), "source": "rule", "calls": calls,
                    "error": "AI 답변에 계산 결과에 없는 숫자가 있어 계산 결과를 그대로 보여 드려요."}
    except Exception as e:  # noqa: BLE001
        logger.warning("대화 에이전트 실패: %s", e)
        return {"answer": _fallback_answer(calls) if calls else "지금은 답을 만들지 못했어요. 잠시 후 다시 물어봐 주세요.",
                "source": "rule", "calls": calls, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    return {"answer": _fallback_answer(calls), "source": "rule", "calls": calls, "error": "도구 호출이 끝나지 않았어요."}
