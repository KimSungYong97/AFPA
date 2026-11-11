"""온보딩 입력 (마이데이터로 알 수 없는 정보) — 「사용자 데이터 입력(온보딩) 설계」"""
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models.entities import ClassifiedFlow, ManualAsset, User, UserProfile
from app.models.schemas import OnboardingInput
from app.services import pipeline_service

MIN_AGE = 19   # 서비스 대상: 만 19세 이상 (온보딩 설계 2.1, 연령 하한 정책은 미결 사항)


def _age(birth: date, today: date) -> int:
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def validate(data: OnboardingInput, today: Optional[date] = None) -> None:
    today = today or date.today()
    if data.birth_date > today:
        raise ValueError("생년월일은 미래일 수 없습니다.")
    if _age(data.birth_date, today) < MIN_AGE:
        raise ValueError(f"만 {MIN_AGE}세 이상만 이용할 수 있습니다.")
    if data.housing_type == "MONTHLY_RENT" and not data.housing_cost_monthly:
        raise ValueError("월세를 선택한 경우 월세 금액이 필요합니다.")


def upsert(db: Session, user_id: int, data: OnboardingInput, today: Optional[date] = None) -> UserProfile:
    if db.get(User, user_id) is None:
        raise LookupError(f"사용자 {user_id}가 없습니다.")
    validate(data, today)

    prof = db.query(UserProfile).filter_by(user_id=user_id).first()
    if prof is None:
        prof = UserProfile(user_id=user_id)
        db.add(prof)
    prof.birth_date = data.birth_date
    prof.gender = data.gender
    prof.employment_status = data.employment_status
    prof.housing_type = data.housing_type
    prof.housing_cost_monthly = data.housing_cost_monthly if data.housing_type == "MONTHLY_RENT" else None
    prof.location_region = data.location_region
    prof.location_district = data.location_district
    prof.risk_tolerance = data.risk_tolerance or "BALANCED"   # 미입력 시 중립형 가정

    if data.manual_assets is not None:
        db.query(ManualAsset).filter_by(user_id=user_id).delete()
        for m in data.manual_assets:
            db.add(ManualAsset(user_id=user_id, asset_type=m.asset_type, name=m.name, amount=m.amount))
    db.commit()
    db.refresh(prof)

    # 고용 형태·거주 형태·수동 자산이 바뀌면 프로필을 재산출한다 (분류 데이터가 있을 때만)
    if db.query(ClassifiedFlow).filter_by(user_id=user_id).count() > 0:
        pipeline_service.compute_and_store_snapshot(db, user_id)
    return prof


def get(db: Session, user_id: int) -> Optional[dict]:
    prof = db.query(UserProfile).filter_by(user_id=user_id).first()
    if prof is None:
        return None
    assets = db.query(ManualAsset).filter_by(user_id=user_id).all()
    return {
        "user_id": user_id, "birth_date": prof.birth_date.isoformat() if prof.birth_date else None,
        "gender": prof.gender, "employment_status": prof.employment_status,
        "housing_type": prof.housing_type, "housing_cost_monthly": prof.housing_cost_monthly,
        "location_region": prof.location_region, "location_district": prof.location_district,
        "risk_tolerance": prof.risk_tolerance,
        "manual_assets": [{"asset_type": a.asset_type, "name": a.name, "amount": a.amount,
                           "updated_at": a.updated_at.isoformat()} for a in assets],
    }
