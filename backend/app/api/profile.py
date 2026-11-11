"""5.1 금융 프로필 API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.schemas import ProfileInput, ProfileSummary
from app.services import pipeline_service, profile_service

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


@router.get("/{user_id}/snapshot")
def latest_snapshot(user_id: int, db: Session = Depends(get_db)):
    """최신 금융 프로필 스냅샷 (6개 엔진 상세 포함)"""
    snap = pipeline_service.latest_snapshot(db, user_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="스냅샷이 없습니다. 마이데이터를 먼저 동기화하세요.")
    return pipeline_service.snapshot_dict(snap)


@router.get("/{user_id}/snapshots")
def snapshot_history(user_id: int, limit: int = 30, db: Session = Depends(get_db)):
    """스냅샷 이력 (추세 분석용, 최신순)"""
    from app.models.entities import FinancialSnapshot
    rows = (db.query(FinancialSnapshot).filter_by(user_id=user_id)
            .order_by(FinancialSnapshot.calculated_at.desc(), FinancialSnapshot.id.desc())
            .limit(limit).all())
    return {"snapshots": [pipeline_service.snapshot_dict(s, with_details=False) for s in rows]}


@router.get("/{user_id}/analysis")
def analysis(user_id: int, db: Session = Depends(get_db)):
    """수입·지출·자산 분석: 월별 추이, 카테고리 비중, 자산 구성, 이상 지출"""
    try:
        return pipeline_service.analysis(db, user_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
