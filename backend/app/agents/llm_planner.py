"""5.4/5.8 LLM 기반 Financial Planning Agent

OpenAI tool-calling 루프:
    1. LLM에게 사용자 목표와 도구 목록 제공
    2. LLM이 필요한 도구(프로필/목표/상품/알림/규칙제안)를 스스로 호출
    3. 수집한 정보를 종합해 구조화된 Action Plan(JSON) 생성

키가 없거나 호출 실패 시 호출부(planner.py)에서 규칙 기반으로 폴백한다.
"""
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.agents.tools import TOOL_SCHEMAS, execute_tool
from app.config import get_settings
from app.models.schemas import ActionItem, ActionPlanOut

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_TOOL_ITERATIONS = 6

SYSTEM_PROMPT = """당신은 개인 금융 전략을 수립하는 Financial Planning Agent입니다.

역할:
- 사용자의 금융 프로필, 목표, 소비 알림, 시장 상품 정보를 도구로 조회하여 종합 분석합니다.
- 목표 달성을 위한 실행 가능한 금융 전략(Action Plan)을 수립합니다.

원칙:
1. 반드시 도구를 호출해 실제 데이터를 확인한 후 판단하세요. 추측하지 마세요.
2. 규칙 기반 제안(get_rule_based_suggestions)을 참고하되, 시장 상품·목표 상황을 종합해 더 나은 전략을 제시하세요.
3. 예·적금 상품을 추천할 때는 조회된 실제 상품명과 금리를 근거로 제시하세요.
4. 개별 주식 종목은 추천하지 않습니다. 자산 배분 관점만 제안합니다.
5. 금액은 구체적인 숫자로 제시하세요.
6. 간결하게 쓰세요: actions는 최대 4개, 각 항목은 한두 문장, rationale·expected_outcome은 각각 3문장 이내.

최종 응답은 반드시 아래 JSON 형식으로만 출력하세요 (다른 텍스트 없이):
{
  "actions": [
    {"category": "saving|spending|card|loan|invest", "action": "실행 내용", "expected_effect": "기대 효과"}
  ],
  "rationale": "추천 근거 (사용자 상황 기반 설명, 데이터 인용)",
  "expected_outcome": "예상 결과 (목표 달성 가능성, 예상 시점)"
}
"""


def generate_llm_action_plan(
    db: Session, user_id: int, goal_id: Optional[int] = None
) -> ActionPlanOut:
    """LLM Agent 실행 → ActionPlanOut 반환. 실패 시 예외 발생 (호출부에서 규칙 기반으로 폴백).

    1) 서버가 tool-calling을 지원하면 LLM이 도구를 직접 호출한다(tool_calling).
    2) 지원하지 않으면(예: vLLM을 --enable-auto-tool-choice 없이 실행) 코드가 도구 결과를 먼저 모두 조회해
       프롬프트에 넣어 주는 방식으로 대신한다(prefetched_context). 계산·조회는 어느 쪽이든 코드가 한다.
    """
    try:
        return _plan_with_tool_calling(db, user_id, goal_id)
    except Exception as e:  # noqa: BLE001
        if "tool" not in str(e).lower():
            raise
        logger.warning("서버가 tool-calling을 지원하지 않아 사전 조회 방식으로 전환: %s", str(e)[:120])
        plan = _plan_with_prefetched_context(db, user_id, goal_id)
        return plan


def _plan_with_prefetched_context(db: Session, user_id: int, goal_id: Optional[int]) -> ActionPlanOut:
    from app.agents.tools import TOOL_REGISTRY
    from app.llm_client import get_llm_client

    client = get_llm_client(timeout=240, max_retries=0)   # 계획 작성은 응답이 길어 오래 걸릴 수 있다
    if client is None:
        raise RuntimeError("LLM이 설정되지 않았습니다 (LLM_BASE_URL 또는 OPENAI_API_KEY)")
    names = list(TOOL_REGISTRY)
    context = {name: json.loads(execute_tool(name, db, user_id)) for name in names}
    user_msg = ("아래는 코드가 미리 조회한 사용자 데이터입니다. 이 데이터만 근거로 금융 전략을 수립해 주세요."
                + (f" 특히 goal_id={goal_id} 목표를 중심으로 분석해 주세요." if goal_id else "")
                + "\n\n" + json.dumps(context, ensure_ascii=False, default=str))
    response = client.chat.completions.create(
        model=settings.llm_model, temperature=0.2, max_tokens=900,
        messages=[{"role": "system", "content": SYSTEM_PROMPT.replace("반드시 도구를 호출해 실제 데이터를 확인한 후 판단하세요. 추측하지 마세요.",
                                                                    "제공된 데이터만 근거로 판단하고 추측하지 마세요.")},
                  {"role": "user", "content": user_msg}],
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    plan = _parse_plan(response.choices[0].message.content or "", goal_id)
    plan.llm_tools_used = names
    plan.llm_mode = "prefetched_context"
    return plan


def _plan_with_tool_calling(db: Session, user_id: int, goal_id: Optional[int] = None) -> ActionPlanOut:
    from app.llm_client import get_llm_client

    client = get_llm_client(timeout=240, max_retries=0)   # 계획 작성은 응답이 길어 오래 걸릴 수 있다
    if client is None:
        raise RuntimeError("LLM이 설정되지 않았습니다 (LLM_BASE_URL 또는 OPENAI_API_KEY)")

    user_msg = f"user_id={user_id} 사용자의 금융 전략을 수립해주세요."
    if goal_id:
        user_msg += f" 특히 goal_id={goal_id} 목표를 중심으로 분석해주세요."

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    tools_used: list[str] = []
    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            tools=TOOL_SCHEMAS,
            temperature=0.2,
        )
        msg = response.choices[0].message

        # 도구 호출 요청 → 실행 후 결과 전달
        if msg.tool_calls:
            messages.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                logger.info("LLM tool call: %s", tc.function.name)
                tools_used.append(tc.function.name)
                result = execute_tool(tc.function.name, db, user_id)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            continue

        # 최종 응답 → JSON 파싱
        plan = _parse_plan(msg.content or "", goal_id)
        plan.llm_tools_used = tools_used
        plan.llm_mode = "tool_calling"
        return plan

    raise RuntimeError("LLM Agent가 최대 반복 횟수 내에 계획을 완성하지 못했습니다.")


def _parse_plan(content: str, goal_id: Optional[int]) -> ActionPlanOut:
    """LLM 응답(JSON)을 ActionPlanOut으로 변환"""
    # 코드블록 감싸짐 대응
    import re
    text = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    if not text.lstrip().startswith("{") and "{" in text:      # JSON 앞뒤에 설명이 붙은 경우
        text = text[text.index("{"): text.rindex("}") + 1]

    data = json.loads(text)
    return ActionPlanOut(
        goal_id=goal_id,
        actions=[ActionItem(**a) for a in data["actions"]],
        rationale=data.get("rationale", ""),
        expected_outcome=data.get("expected_outcome", ""),
        created_at=datetime.utcnow(),
    )
