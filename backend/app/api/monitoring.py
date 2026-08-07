"""5.5 / 5.6 모니터링 API"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.schemas import MonitoringAlert
from app.services import monitoring_service

router = APIRouter()


@router.get("/{user_id}/spending", response_model=list[MonitoringAlert])
def check_spending(user_id: int, db: Session = Depends(get_db)):
    """5.5 소비 변화 감지"""
    return monitoring_service.detect_spending_changes(db, user_id)


@router.get("/{user_id}/market", response_model=list[MonitoringAlert])
async def check_market(user_id: int, db: Session = Depends(get_db)):
    """5.6 금융 환경 변화 감지"""
    return await monitoring_service.detect_market_changes(db, user_id)
