"""5.4 Financial Planning Agent

전략:
    1) OpenAI API 키가 설정되어 있으면 → LLM Agent (llm_planner)가 도구를 호출하며 계획 수립
    2) 키가 없거나 LLM 호출 실패 시     → 규칙 기반 폴백 (Phase 1 MVP 규칙)

규칙 기반 로직은 LLM Agent의 도구(get_rule_based_suggestions)로도 재사용된다.
"""
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import ActionPlan
from app.models.schemas import ActionItem, ActionPlanOut
from app.services import goal_service, profile_service

logger = logging.getLogger(__name__)
settings = get_settings()


def generate_action_plan(db: Session, user_id: int, goal_id: Optional[int] = None) -> ActionPlanOut:
    """Action Plan 생성 — LLM 우선, 실패 시 규칙 기반 폴백"""
    plan: Optional[ActionPlanOut] = None

    if settings.openai_api_key:
        try:
            from app.agents.llm_planner import generate_llm_action_plan

            plan = generate_llm_action_plan(db, user_id, goal_id)
            logger.info("LLM Agent가 Action Plan 생성 (user_id=%s)", user_id)
        except Exception as e:  # noqa: BLE001 - LLM 실패 시 규칙 기반으로 폴백
            logger.warning("LLM Agent 실패, 규칙 기반으로 폴백: %s", e)

    if plan is None:
        plan = _generate_rule_based_plan(db, user_id, goal_id)

    _save_plan(db, user_id, plan)
    return plan


# ---------------------------------------------------------------------------
# 규칙 기반 (폴백 + LLM 도구 재료)
# ---------------------------------------------------------------------------
def _rule_based_actions(db: Session, user_id: int) -> tuple[list[ActionItem], list[str]]:
    """Phase 1 규칙: 비상금 / 저축률 / 부채. (actions, rationale_parts) 반환"""
    summary = profile_service.get_summary(db, user_id)
    if summary is None:
        raise ValueError("금융 프로필이 없습니다. 먼저 프로필을 등록하세요.")

    actions: list[ActionItem] = []
    rationale_parts: list[str] = []

    if summary.cash_ratio < 20:
        actions.append(ActionItem(
            category="saving",
            action="현금성 자산(예·적금) 비중을 총자산의 20% 이상으로 확대",
            expected_effect="긴급 상황 대응력 향상",
        ))
        rationale_parts.append(f"현금 보유율이 {summary.cash_ratio}%로 낮은 편입니다.")

    if summary.savings_rate < 20:
        actions.append(ActionItem(
            category="spending",
            action="변동 지출을 점검하여 월 저축률 20% 이상 확보",
            expected_effect="목표 달성 속도 개선",
        ))
        rationale_parts.append(f"저축률이 {summary.savings_rate}%로 권장 수준(20%) 미만입니다.")

    if summary.debt_to_asset_ratio > 40:
        actions.append(ActionItem(
            category="loan",
            action="고금리 부채부터 우선 상환하는 상환 계획 수립",
            expected_effect="이자 비용 절감 및 금융 건강도 개선",
        ))
        rationale_parts.append(f"자산 대비 부채 비율이 {summary.debt_to_asset_ratio}%로 높습니다.")

    return actions, rationale_parts


def _generate_rule_based_plan(
    db: Session, user_id: int, goal_id: Optional[int] = None
) -> ActionPlanOut:
    actions, rationale_parts = _rule_based_actions(db, user_id)

    expected_outcome = "금융 건강도 개선"
    if goal_id:
        feasibility = goal_service.analyze_feasibility(db, goal_id)
        if feasibility:
            if not feasibility.achievable:
                actions.append(ActionItem(
                    category="saving",
                    action=f"목표 달성을 위해 월 {feasibility.required_monthly_saving:,.0f}원 저축 필요",
                    expected_effect="목표 기한 내 달성 가능",
                ))
                rationale_parts.append("현재 여유 자금으로는 목표 기한 내 달성이 어렵습니다.")
            if feasibility.expected_completion:
                expected_outcome = f"예상 달성 시점: {feasibility.expected_completion.isoformat()}"

    if not actions:
        actions.append(ActionItem(
            category="invest",
            action="여유 자금의 투자 배분 검토 (Phase 4에서 고도화 예정)",
            expected_effect="자산 증식 기회 확보",
        ))
        rationale_parts.append("전반적인 금융 상태가 양호합니다.")

    return ActionPlanOut(
        goal_id=goal_id,
        actions=actions,
        rationale=" ".join(rationale_parts),
        expected_outcome=expected_outcome,
        created_at=datetime.utcnow(),
    )


def _save_plan(db: Session, user_id: int, plan: ActionPlanOut) -> None:
    entity = ActionPlan(
        user_id=user_id,
        goal_id=plan.goal_id,
        plan_json=json.dumps([a.model_dump() for a in plan.actions], ensure_ascii=False),
        rationale=plan.rationale,
    )
    db.add(entity)
    db.commit()
