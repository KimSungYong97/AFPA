"""5.4 / 5.7 / 5.8 Planning API"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents import planner, replanner
from app.db.session import get_db
from app.models.schemas import ActionPlanOut

router = APIRouter()


@router.post("/{user_id}/action-plan", response_model=ActionPlanOut)
def create_action_plan(user_id: int, goal_id: Optional[int] = None, db: Session = Depends(get_db)):
    """5.4/5.8 Action Plan 생성"""
    try:
        return planner.generate_action_plan(db, user_id, goal_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{user_id}/replan", response_model=Optional[ActionPlanOut])
def replan(user_id: int, goal_id: Optional[int] = None, db: Session = Depends(get_db)):
    """5.7 변화 감지 기반 재계획 (변화 없으면 null 반환)"""
    return replanner.replan_if_needed(db, user_id, goal_id)
