"""5.2 목표 관리 API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.schemas import GoalCreate, GoalFeasibility, GoalOut
from app.services import goal_service

router = APIRouter()


@router.post("/{user_id}", response_model=GoalOut)
def create_goal(user_id: int, data: GoalCreate, db: Session = Depends(get_db)):
    return goal_service.create_goal(db, user_id, data)


@router.get("/{user_id}", response_model=list[GoalOut])
def list_goals(user_id: int, db: Session = Depends(get_db)):
    return goal_service.list_goals(db, user_id)


@router.put("/item/{goal_id}", response_model=GoalOut)
def update_goal(goal_id: int, data: GoalCreate, db: Session = Depends(get_db)):
    goal = goal_service.update_goal(db, goal_id, data)
    if goal is None:
        raise HTTPException(status_code=404, detail="목표를 찾을 수 없습니다.")
    return goal


@router.delete("/item/{goal_id}")
def delete_goal(goal_id: int, db: Session = Depends(get_db)):
    if not goal_service.delete_goal(db, goal_id):
        raise HTTPException(status_code=404, detail="목표를 찾을 수 없습니다.")
    return {"deleted": True}


@router.get("/item/{goal_id}/feasibility", response_model=GoalFeasibility)
def analyze_feasibility(goal_id: int, db: Session = Depends(get_db)):
    """목표 달성 가능성 분석"""
    result = goal_service.analyze_feasibility(db, goal_id)
    if result is None:
        raise HTTPException(status_code=404, detail="목표를 찾을 수 없습니다.")
    return result
