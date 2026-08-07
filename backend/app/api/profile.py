"""5.1 금융 프로필 API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.schemas import ProfileInput, ProfileSummary
from app.services import profile_service

router = APIRouter()


@router.put("/{user_id}")
def upsert_profile(user_id: int, data: ProfileInput, db: Session = Depends(get_db)):
    """금융 프로필 등록/수정"""
    profile_service.get_or_create_user(db, user_id)
    profile = profile_service.upsert_profile(db, user_id, data)
    return {"user_id": user_id, "health_score": profile.health_score}


@router.get("/{user_id}/summary", response_model=ProfileSummary)
def get_summary(user_id: int, db: Session = Depends(get_db)):
    """자산 요약 / 금융 건강도 조회"""
    summary = profile_service.get_summary(db, user_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="프로필이 없습니다.")
    return summary
