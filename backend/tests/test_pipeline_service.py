"""DB 연동 파이프라인: 동의 게이트, 동기화, 스냅샷 누적, 사용자 수정(4단계), 온보딩"""
from datetime import date

import pytest

from app.models.entities import (
    ClassifiedFlow, FinancialProfile, FinancialSnapshot, Goal, MerchantCategoryOverride, Transaction, User,
)
from app.models.schemas import ManualAssetIn, OnboardingInput
from app.pipeline.mydata_source import load_user_data, user_dir
from app.services import onboarding_service, pipeline_service


def _seed_user(db, uid=1):
    db.add(User(id=uid, name="테스터"))
    db.add(Goal(user_id=uid, name="전세보증금", goal_type="long_term", target_amount=50_000_000,
                current_amount=14_000_000, target_date=date(2028, 12, 31), priority=1))
    db.commit()


def _onboarding(**kw):
    base = dict(birth_date=date(1998, 3, 14), employment_status="FULL_TIME", housing_type="JEONSE",
                location_region="서울", location_district="서초구")
    base.update(kw)
    return OnboardingInput(**base)


# ---------------------------------------------------------------- 동의 게이트
def test_sync_requires_consent(db):
    _seed_user(db)
    with pytest.raises(PermissionError):
        pipeline_service.sync_user(db, 1, load_user_data(user_dir(1)), use_llm=False)


def test_partial_consent_is_rejected_in_phase1(db):
    _seed_user(db)
    with pytest.raises(ValueError):
        pipeline_service.record_consent(db, 1, merchant=True, memo=False, category=True)   # D-09


# ---------------------------------------------------------------- 동기화 → 스냅샷
def test_sync_stores_flows_holdings_snapshot_and_legacy_tables(db):
    _seed_user(db)
    pipeline_service.record_consent(db, 1)
    result = pipeline_service.sync_user(db, 1, load_user_data(user_dir(1)), use_llm=False)

    assert result["flows"] > 100 and result["snapshot_id"]
    snap = pipeline_service.latest_snapshot(db, 1)
    assert snap.monthly_income_net == 3_200_000
    assert snap.net_cash_flow == pytest.approx(3_200_000 - 1_100_200 - 936_840, abs=1)
    assert 0 <= snap.health_score <= 100 and 0 <= snap.potential_score <= 100
    assert db.get(User, 1).mydata_connected is True

    # 기존 Planning Agent·모니터링용 테이블이 호환 브리지로 채워진다
    profile = db.query(FinancialProfile).filter_by(user_id=1).one()
    assert profile.monthly_income == 3_200_000 and profile.health_score == snap.health_score
    assert db.query(Transaction).filter_by(user_id=1).count() > 100


def test_each_sync_appends_a_snapshot_but_replaces_flows(db):
    _seed_user(db)
    pipeline_service.record_consent(db, 1)
    data = load_user_data(user_dir(1))
    pipeline_service.sync_user(db, 1, data, use_llm=False)
    n1 = db.query(ClassifiedFlow).filter_by(user_id=1).count()
    pipeline_service.sync_user(db, 1, data, use_llm=False)
    assert db.query(ClassifiedFlow).filter_by(user_id=1).count() == n1      # 분류 결과는 교체
    assert db.query(FinancialSnapshot).filter_by(user_id=1).count() == 2    # 스냅샷은 누적(추세 분석 기반)


# ---------------------------------------------------------------- 사용자 수정 (분류 4단계)
def test_merchant_override_is_learned_and_reapplied_on_next_sync(db):
    _seed_user(db)
    pipeline_service.record_consent(db, 1)
    data = load_user_data(user_dir(1))
    pipeline_service.sync_user(db, 1, data, use_llm=False)
    before = pipeline_service.latest_snapshot(db, 1)

    out = pipeline_service.apply_override(db, 1, "스타벅스 역삼점", "식비")
    assert out["updated_flows"] > 0
    rows = db.query(ClassifiedFlow).filter_by(user_id=1, merchant_norm="스타벅스").all()
    assert rows and all(r.category == "식비" and r.stage == 1 and not r.needs_review for r in rows)
    assert pipeline_service.latest_snapshot(db, 1).id != before.id           # 수정 즉시 재산출

    # 다음 동기화에서도 사전보다 우선 적용된다
    pipeline_service.sync_user(db, 1, data, use_llm=False)
    assert all(r.category == "식비" for r in
               db.query(ClassifiedFlow).filter_by(user_id=1, merchant_norm="스타벅스"))
    assert db.query(MerchantCategoryOverride).filter_by(user_id=1).count() == 1


def test_review_list_and_nameless_flow_override(db):
    _seed_user(db)
    pipeline_service.record_consent(db, 1)
    pipeline_service.sync_user(db, 1, load_user_data(user_dir(1)), use_llm=False)
    items = pipeline_service.review_items(db, 1)
    assert items and items[0]["current_category"] == "미분류"

    nameless = [i for i in items if i["merchant_norm"] == ""][0]               # 가맹점명 없는 건(0단계)
    with pytest.raises(ValueError):
        pipeline_service.apply_override(db, 1, nameless["merchant"], "식비")      # 규칙으로는 저장 불가
    pipeline_service.apply_flow_override(db, 1, nameless["flow_ids"][0], "쇼핑")   # 한 건 단위로는 가능
    after = pipeline_service.review_items(db, 1)
    remaining = sum(i["count"] for i in after)
    assert remaining == sum(i["count"] for i in items) - 1


def test_override_rejects_unknown_category(db):
    _seed_user(db)
    with pytest.raises(ValueError):
        pipeline_service.apply_override(db, 1, "스타벅스", "없는카테고리")


# ---------------------------------------------------------------- 온보딩
def test_onboarding_validation(db):
    _seed_user(db)
    today = date(2026, 8, 7)
    with pytest.raises(ValueError):                      # 만 19세 미만
        onboarding_service.upsert(db, 1, _onboarding(birth_date=date(2010, 1, 1)), today)
    with pytest.raises(ValueError):                      # 미래 생년월일
        onboarding_service.upsert(db, 1, _onboarding(birth_date=date(2030, 1, 1)), today)
    with pytest.raises(ValueError):                      # 월세인데 월세 금액 없음
        onboarding_service.upsert(db, 1, _onboarding(housing_type="MONTHLY_RENT"), today)
    with pytest.raises(LookupError):
        onboarding_service.upsert(db, 99, _onboarding(), today)


def test_onboarding_defaults_and_rent_cost_cleanup(db):
    _seed_user(db)
    onboarding_service.upsert(db, 1, _onboarding(housing_cost_monthly=500_000, risk_tolerance=None))
    prof = onboarding_service.get(db, 1)
    assert prof["risk_tolerance"] == "BALANCED"             # 미입력 시 중립형 가정
    assert prof["housing_cost_monthly"] is None            # 월세가 아니면 금액은 저장하지 않는다


def test_manual_assets_enter_net_worth_but_not_emergency_fund(db):
    _seed_user(db)
    pipeline_service.record_consent(db, 1)
    data = load_user_data(user_dir(1))
    pipeline_service.sync_user(db, 1, data, use_llm=False)
    base = pipeline_service.latest_snapshot(db, 1)

    # 온보딩의 수동 자산 변경은 프로필 재산출을 일으킨다
    onboarding_service.upsert(db, 1, _onboarding(manual_assets=[
        ManualAssetIn(asset_type="GOLD", name="금", amount=3_000_000),
        ManualAssetIn(asset_type="CASH", name="현금", amount=200_000)]))
    after = pipeline_service.latest_snapshot(db, 1)
    assert after.id != base.id
    assert after.net_worth == base.net_worth + 3_200_000
    assert after.emergency_fund_ratio == base.emergency_fund_ratio          # 현금·금은 비상금 제외 (D-06)


def test_employment_change_triggers_recalculation(db):
    _seed_user(db)
    pipeline_service.record_consent(db, 1)
    pipeline_service.sync_user(db, 1, load_user_data(user_dir(1)), use_llm=False)
    onboarding_service.upsert(db, 1, _onboarding(employment_status="FULL_TIME"))
    full = pipeline_service.latest_snapshot(db, 1).emergency_fund_ratio
    onboarding_service.upsert(db, 1, _onboarding(employment_status="FREELANCER"))
    free = pipeline_service.latest_snapshot(db, 1).emergency_fund_ratio
    assert free == pytest.approx(full / 2, abs=0.01)                          # 필요 비상금 3→6개월
