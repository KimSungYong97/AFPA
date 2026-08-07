"""LLM Agent가 사용하는 도구(Tool) 모음

각 도구는 DB/서비스 계층을 감싸 LLM이 호출할 수 있는 형태(JSON 직렬화 가능)로 제공한다.
기존 규칙 기반 로직(planner 규칙)도 도구로 노출하여 LLM이 참고 자료로 활용한다.
"""
import asyncio
import json
from typing import Any

from sqlalchemy.orm import Session

from app.services import goal_service, market_service, monitoring_service, profile_service


# ---------------------------------------------------------------------------
# 도구 구현 (DB 세션은 실행 시 주입)
# ---------------------------------------------------------------------------
def get_profile_summary(db: Session, user_id: int) -> dict:
    """사용자 금융 프로필 요약 (자산/부채/저축률/건강도)"""
    s = profile_service.get_summary(db, user_id)
    if s is None:
        return {"error": "금융 프로필이 없습니다."}
    return s.model_dump()


def get_goals_with_feasibility(db: Session, user_id: int) -> list[dict]:
    """사용자의 모든 목표와 각 목표의 달성 가능성 분석"""
    result = []
    for g in goal_service.list_goals(db, user_id):
        f = goal_service.analyze_feasibility(db, g.id)
        result.append({
            "goal_id": g.id,
            "name": g.name,
            "goal_type": g.goal_type,
            "target_amount": g.target_amount,
            "current_amount": g.current_amount,
            "target_date": g.target_date.isoformat() if g.target_date else None,
            "priority": g.priority,
            "feasibility": f.model_dump(mode="json") if f else None,
        })
    return result


def get_market_products(db: Session, user_id: int) -> dict:
    """현재 시장의 예금/적금 상품 목록과 기준금리"""
    return {
        "base_rate": asyncio.run(market_service.get_base_rate()),
        "deposit_products": asyncio.run(market_service.fetch_deposit_products()),
        "savings_products": asyncio.run(market_service.fetch_savings_products()),
    }


def get_spending_alerts(db: Session, user_id: int) -> list[dict]:
    """소비 패턴 변화 알림 (이번 달 소비 vs 3개월 평균)"""
    alerts = monitoring_service.detect_spending_changes(db, user_id)
    return [a.model_dump(mode="json") for a in alerts]


def get_rule_based_suggestions(db: Session, user_id: int) -> list[dict]:
    """규칙 기반 기본 제안 (비상금/저축률/부채 규칙) — LLM 참고용"""
    from app.agents.planner import _rule_based_actions  # 순환 임포트 방지

    actions, rationale_parts = _rule_based_actions(db, user_id)
    return [
        {"actions": [a.model_dump() for a in actions], "rationale_hints": rationale_parts}
    ]


# ---------------------------------------------------------------------------
# OpenAI tool 스키마 정의
# ---------------------------------------------------------------------------
TOOL_REGISTRY = {
    "get_profile_summary": get_profile_summary,
    "get_goals_with_feasibility": get_goals_with_feasibility,
    "get_market_products": get_market_products,
    "get_spending_alerts": get_spending_alerts,
    "get_rule_based_suggestions": get_rule_based_suggestions,
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": fn.__doc__ or name,
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
    for name, fn in TOOL_REGISTRY.items()
]


def execute_tool(name: str, db: Session, user_id: int) -> str:
    """도구 실행 후 결과를 JSON 문자열로 반환"""
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
    try:
        result = fn(db, user_id)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:  # noqa: BLE001 - 도구 오류를 LLM에게 전달
        return json.dumps({"error": str(e)}, ensure_ascii=False)
