"""사용자 목록 API (프론트엔드 사용자 선택용)"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import User

router = APIRouter()


@router.get("")
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.id).all()
    return [
        {"id": u.id, "name": u.name, "job": u.job, "persona_type": u.persona_type,
         "description": u.description, "mydata_connected": u.mydata_connected,
         "mydata_last_synced_at": u.mydata_last_synced_at.isoformat() if u.mydata_last_synced_at else None}
        for u in users
    ]
