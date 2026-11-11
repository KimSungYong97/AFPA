"""온보딩 API — 마이데이터로 알 수 없는 정보 입력"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.schemas import OnboardingInput
from app.services import onboarding_service

router = APIRouter()


@router.put("/{user_id}")
def upsert_onboarding(user_id: int, data: OnboardingInput, db: Session = Depends(get_db)):
    """온보딩 정보 등록/수정 (수정 시 프로필 재산출)"""
    try:
        onboarding_service.upsert(db, user_id, data)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return onboarding_service.get(db, user_id)


@router.get("/{user_id}")
def get_onboarding(user_id: int, db: Session = Depends(get_db)):
    result = onboarding_service.get(db, user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="온보딩 정보가 없습니다.")
    return result
