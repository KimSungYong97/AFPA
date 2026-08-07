"""5.2 목표 관리 서비스
- 목표 CRUD / 필요 자금 계산 / 달성 가능성 분석
"""
from datetime import date
from typing import Optional

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from app.models.entities import FinancialProfile, Goal
from app.models.schemas import GoalCreate, GoalFeasibility


def create_goal(db: Session, user_id: int, data: GoalCreate) -> Goal:
    goal = Goal(user_id=user_id, **data.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def list_goals(db: Session, user_id: int) -> list[Goal]:
    return (
        db.query(Goal)
        .filter_by(user_id=user_id)
        .order_by(Goal.priority.asc(), Goal.target_date.asc())
        .all()
    )


def update_goal(db: Session, goal_id: int, data: GoalCreate) -> Optional[Goal]:
    goal = db.get(Goal, goal_id)
    if goal is None:
        return None
    for field, value in data.model_dump().items():
        setattr(goal, field, value)
    db.commit()
    db.refresh(goal)
    return goal


def delete_goal(db: Session, goal_id: int) -> bool:
    goal = db.get(Goal, goal_id)
    if goal is None:
        return False
    db.delete(goal)
    db.commit()
    return True


def analyze_feasibility(db: Session, goal_id: int) -> Optional[GoalFeasibility]:
    """목표 달성 가능성 분석
    - 필요 월 저축액 vs 현재 월 여유 자금 비교
    """
    goal = db.get(Goal, goal_id)
    if goal is None:
        return None

    profile = db.query(FinancialProfile).filter_by(user_id=goal.user_id).first()
    monthly_surplus = 0.0
    if profile:
        monthly_surplus = profile.monthly_income - (
            profile.monthly_fixed_expense + profile.monthly_variable_expense
        )

    shortfall = max(goal.target_amount - goal.current_amount, 0)

    # 목표일까지 필요한 월 저축액
    required_monthly = 0.0
    if goal.target_date:
        months_left = _months_between(date.today(), goal.target_date)
        required_monthly = shortfall / months_left if months_left > 0 else shortfall

    # 현재 저축 속도 기준 달성 예상 시기
    expected_completion = None
    if monthly_surplus > 0 and shortfall > 0:
        months_needed = int(shortfall / monthly_surplus) + 1
        expected_completion = date.today() + relativedelta(months=months_needed)
    elif shortfall == 0:
        expected_completion = date.today()

    achievable = monthly_surplus >= required_monthly if goal.target_date else monthly_surplus > 0

    return GoalFeasibility(
        goal_id=goal.id,
        required_monthly_saving=round(required_monthly),
        expected_completion=expected_completion,
        shortfall=shortfall,
        achievable=achievable,
    )


def _months_between(start: date, end: date) -> int:
    return max((end.year - start.year) * 12 + (end.month - start.month), 0)
