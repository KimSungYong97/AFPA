"""5.7 Re-Planning Agent
- 모니터링 알림 발생 시 기존 계획을 재검토하고 새 Action Plan 생성
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.agents import planner
from app.models.schemas import ActionPlanOut, MonitoringAlert
from app.services import monitoring_service


def replan_if_needed(db: Session, user_id: int, goal_id: Optional[int] = None) -> Optional[ActionPlanOut]:
    """소비/환경 변화 감지 → 필요 시 재계획"""
    alerts: list[MonitoringAlert] = monitoring_service.detect_spending_changes(db, user_id)

    if not alerts:
        return None  # 변화 없음 → 재계획 불필요

    # 변화 감지 → 새 Action Plan 생성 (알림 내용을 근거에 반영)
    plan = planner.generate_action_plan(db, user_id, goal_id)
    alert_msgs = " / ".join(a.message for a in alerts)
    plan.rationale = f"[재계획 사유] {alert_msgs} — {plan.rationale}"
    return plan
