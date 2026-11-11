"""1차 파이프라인 오케스트레이션 (DB 연동)

마이데이터 → 자동 분류 → 분류 결과·보유 내역 저장 → 6개 엔진 → 스냅샷 누적
사용자 분류 수정(4단계)은 override로 저장하고 즉시 반영·재산출한다.
"""
import json
from collections import defaultdict
from datetime import date, datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.entities import (
    AccountHolding, ClassifiedFlow, FinancialSnapshot, Goal, ManualAsset, MerchantCandidate,
    MerchantCategoryOverride, MydataConsent, User, UserProfile,
)
from app.pipeline import classifier as clf
from app.pipeline.dictionary import ALL_CATEGORIES, major_for_category
from app.pipeline.engines import EngineInput, EngineResult, compute
from app.pipeline.llm_stage import build_llm_categorizer
from app.pipeline.merchant import MerchantClassifier
from app.pipeline.text import normalize_merchant
from app.pipeline.types import Flow, GoalInfo, Holding, OnboardingInfo
from app.services import legacy_bridge


# ---------------------------------------------------------------------------
# 동의 (1차는 전체 동의 전제 — D-09)
# ---------------------------------------------------------------------------
def record_consent(db: Session, user_id: int, merchant: bool = True, memo: bool = True,
                   category: bool = True) -> MydataConsent:
    if not (merchant and memo and category):
        raise ValueError("1차는 마이데이터 전체 동의를 전제로 합니다. (미동의 대체 경로는 2차 이후)")
    row = MydataConsent(
        user_id=user_id, is_consent_merchant_name_regno=merchant,
        is_consent_trans_memo=memo, is_consent_trans_category=category,
    )
    db.add(row)
    db.commit()
    return row


def has_consent(db: Session, user_id: int) -> bool:
    return db.query(MydataConsent).filter(
        MydataConsent.user_id == user_id, MydataConsent.revoked_at.is_(None)).count() > 0


# ---------------------------------------------------------------------------
# 동기화
# ---------------------------------------------------------------------------
def sync_user(db: Session, user_id: int, data: Dict[str, dict], as_of: Optional[date] = None,
              use_llm: bool = True) -> dict:
    """마이데이터 응답 → 분류 → 저장 → 스냅샷. 동의 이력이 없으면 거부한다."""
    if db.get(User, user_id) is None:
        raise LookupError(f"사용자 {user_id}가 없습니다.")
    if not has_consent(db, user_id):
        raise PermissionError("마이데이터 동의 이력이 없습니다. 먼저 동의를 기록하세요.")

    overrides = {o.merchant_name_norm: o.category
                 for o in db.query(MerchantCategoryOverride).filter_by(user_id=user_id)}
    cache = {c.merchant_name_norm: c.category
             for c in db.query(MerchantCandidate).filter(MerchantCandidate.status != "rejected")}
    merchant = MerchantClassifier(overrides=overrides, llm=build_llm_categorizer() if use_llm else None,
                                  llm_cache=cache)

    flows, report = clf.classify_flows(data, merchant)
    holdings = clf.classify_holdings(data)

    # LLM이 새로 판별한 상호는 후보로 저장 (검수 후 사전 편입, 자동 승격 금지)
    for norm, cat in merchant.new_candidates.items():
        db.add(MerchantCandidate(merchant_name_norm=norm, category=cat))

    db.query(ClassifiedFlow).filter_by(user_id=user_id).delete()
    db.query(AccountHolding).filter_by(user_id=user_id).delete()
    for f in flows:
        db.add(_flow_row(user_id, f))
    for h in holdings:
        db.add(AccountHolding(user_id=user_id, side=h.side, kind=h.kind, sub=h.sub, name=h.name,
                              amount=h.amount, emergency_eligible=h.emergency_eligible))

    user = db.get(User, user_id)
    user.mydata_connected = True
    user.mydata_last_synced_at = datetime.utcnow()
    db.commit()

    snap = compute_and_store_snapshot(db, user_id, as_of)

    # 2차: 동기화 직후 소비 변화 감지 → 이행 추적 → 경로 이탈 시 재설계 제안
    from app.services import planner_service
    planner = planner_service.after_sync(db, user_id)
    return {
        "planner": planner,
        "user_id": user_id,
        "flows": report.total,
        "by_stage": report.by_stage,
        "needs_review": report.needs_review,
        "llm_calls": report.llm_calls,
        "holdings": len(holdings),
        "snapshot_id": snap.id,
        "as_of": snap.as_of.isoformat(),
    }


def _flow_row(user_id: int, f: Flow) -> ClassifiedFlow:
    norm = normalize_merchant(f.counterparty) if f.source in ("card", "efin", "bank") else ""
    return ClassifiedFlow(
        user_id=user_id, occurred_on=f.occurred_on, amount=f.amount, direction=f.direction,
        source=f.source, counterparty=f.counterparty[:200], merchant_norm=norm[:120],
        major_class=f.major, category=f.category, stage=f.stage, rule=f.rule,
        confidence=f.confidence, needs_review=f.needs_review, is_recurring=f.recurring,
    )


def _to_flow(r: ClassifiedFlow) -> Flow:
    return Flow(r.occurred_on, r.amount, r.direction, r.source, r.counterparty, r.major_class,
                r.category, r.stage, r.rule, r.confidence, r.needs_review, r.is_recurring)


# ---------------------------------------------------------------------------
# 스냅샷
# ---------------------------------------------------------------------------
def load_engine_input(db: Session, user_id: int, as_of: Optional[date] = None) -> EngineInput:
    flows = [_to_flow(r) for r in db.query(ClassifiedFlow).filter_by(user_id=user_id)]
    if not flows:
        raise LookupError("분류된 데이터가 없습니다. 먼저 마이데이터를 동기화하세요.")
    holdings = [Holding(h.side, h.kind, h.sub, h.name, h.amount, h.emergency_eligible)
                for h in db.query(AccountHolding).filter_by(user_id=user_id)]
    holdings += _manual_holdings(db, user_id)

    prof = db.query(UserProfile).filter_by(user_id=user_id).first()
    onboarding = OnboardingInfo(
        birth_date=prof.birth_date if prof else None,
        employment_status=prof.employment_status if prof else "FULL_TIME",
        housing_type=prof.housing_type if prof else None,
        housing_cost_monthly=prof.housing_cost_monthly if prof else None,
        risk_tolerance=prof.risk_tolerance if prof else "BALANCED",
    )
    goals = [GoalInfo(g.name, g.target_amount, g.current_amount, g.target_date, g.priority)
             for g in db.query(Goal).filter_by(user_id=user_id)]
    return EngineInput(as_of=as_of or max(f.occurred_on for f in flows), flows=flows,
                       holdings=holdings, onboarding=onboarding, goals=goals)


def _manual_holdings(db: Session, user_id: int) -> List[Holding]:
    out = []
    for m in db.query(ManualAsset).filter_by(user_id=user_id):
        if m.asset_type == "CASH":      # 보유 현금: 참고용, 비상금에는 포함하지 않음
            out.append(Holding("asset", "cash", "보유 현금", m.name or "보유 현금", m.amount,
                               emergency_eligible=False, source="manual"))
        elif m.asset_type == "GOLD":    # D-05: 금 현물은 수동 입력
            out.append(Holding("asset", "invest", "금 현물", m.name or "금 현물", m.amount, source="manual"))
        else:
            out.append(Holding("asset", "other", "기타", m.name or "기타 자산", m.amount, source="manual"))
    return out


def compute_and_store_snapshot(db: Session, user_id: int, as_of: Optional[date] = None) -> FinancialSnapshot:
    inp = load_engine_input(db, user_id, as_of)
    res: EngineResult = compute(inp)
    snap = FinancialSnapshot(
        user_id=user_id, as_of=inp.as_of, monthly_income_net=res.monthly_income_net,
        savings_ratio=res.savings_ratio, dsr_ratio=res.dsr_ratio,
        emergency_fund_ratio=res.emergency_fund_ratio, consumption_ratio=res.consumption_ratio,
        health_score=res.health_score, potential_score=res.potential_score,
        net_cash_flow=res.net_cash_flow, net_worth=res.net_worth, debt_ratio=res.debt_ratio,
        details_json=json.dumps(res.details, ensure_ascii=False),
    )
    db.add(snap)
    legacy_bridge.sync_legacy_tables(db, user_id, inp.flows, inp.holdings, res)
    db.commit()
    db.refresh(snap)
    return snap


def latest_snapshot(db: Session, user_id: int) -> Optional[FinancialSnapshot]:
    return (db.query(FinancialSnapshot).filter_by(user_id=user_id)
            .order_by(FinancialSnapshot.calculated_at.desc(), FinancialSnapshot.id.desc()).first())


def snapshot_dict(s: FinancialSnapshot, with_details: bool = True) -> dict:
    d = {
        "snapshot_id": s.id, "calculated_at": s.calculated_at.isoformat(), "as_of": s.as_of.isoformat(),
        "monthly_income_net": s.monthly_income_net, "net_cash_flow": s.net_cash_flow,
        "net_worth": s.net_worth, "savings_ratio": s.savings_ratio, "dsr_ratio": s.dsr_ratio,
        "emergency_fund_ratio": s.emergency_fund_ratio, "consumption_ratio": s.consumption_ratio,
        "debt_ratio": s.debt_ratio, "health_score": s.health_score, "potential_score": s.potential_score,
    }
    if with_details:
        d["details"] = json.loads(s.details_json or "{}")
    return d


# ---------------------------------------------------------------------------
# 사용자 확인 (분류 4단계)
# ---------------------------------------------------------------------------
def review_items(db: Session, user_id: int) -> List[dict]:
    """미분류·낮은 확신 건을 상호 단위로 모아 사용자가 한 번에 확정할 수 있게 한다."""
    groups: Dict[str, dict] = defaultdict(lambda: {"count": 0, "total": 0.0, "sources": set(),
                                                   "category": None, "stage": 0, "rule": "", "flow_ids": []})
    for r in db.query(ClassifiedFlow).filter_by(user_id=user_id, needs_review=True):
        key = r.counterparty
        g = groups[key]
        g["count"] += 1
        g["flow_ids"].append(r.id)
        g["total"] += r.amount
        g["sources"].add(r.source)
        g["category"], g["stage"], g["rule"] = r.category, r.stage, r.rule
        g["merchant_norm"] = r.merchant_norm
    items = [{"merchant": k, "merchant_norm": v.get("merchant_norm", ""), "count": v["count"],
              "total_amount": round(v["total"]), "sources": sorted(v["sources"]),
              "current_category": v["category"], "stage": v["stage"], "rule": v["rule"],
              "flow_ids": v["flow_ids"][:50]}
             for k, v in groups.items()]
    return sorted(items, key=lambda i: -i["total_amount"])


def apply_override(db: Session, user_id: int, merchant_name: str, category: str) -> dict:
    """사용자 지정 카테고리를 저장하고, 해당 상호의 기존 분류를 갱신한 뒤 스냅샷을 재산출한다."""
    if category not in ALL_CATEGORIES:
        raise ValueError(f"알 수 없는 카테고리입니다: {category}")
    norm = normalize_merchant(merchant_name)
    if not norm:
        raise ValueError("가맹점명이 비어 있어 규칙으로 저장할 수 없습니다.")

    ov = db.query(MerchantCategoryOverride).filter_by(user_id=user_id, merchant_name_norm=norm).first()
    if ov is None:
        db.add(MerchantCategoryOverride(user_id=user_id, merchant_name_norm=norm, category=category))
    else:
        ov.category = category

    updated = 0
    for r in db.query(ClassifiedFlow).filter_by(user_id=user_id, merchant_norm=norm, direction="out"):
        r.category = category
        r.major_class = major_for_category(category)
        r.stage, r.rule, r.confidence, r.needs_review = 1, "user_override", 1.0, False
        updated += 1
    db.commit()
    snap = compute_and_store_snapshot(db, user_id)
    return {"merchant_norm": norm, "category": category, "updated_flows": updated,
            "snapshot_id": snap.id}


def apply_flow_override(db: Session, user_id: int, flow_id: int, category: str) -> dict:
    """가맹점명이 없는 건처럼 규칙으로 저장할 수 없는 거래를 한 건 단위로 확정한다."""
    if category not in ALL_CATEGORIES:
        raise ValueError(f"알 수 없는 카테고리입니다: {category}")
    r = db.get(ClassifiedFlow, flow_id)
    if r is None or r.user_id != user_id:
        raise LookupError("거래를 찾을 수 없습니다.")
    r.category = category
    r.major_class = major_for_category(category)
    r.stage, r.rule, r.confidence, r.needs_review = 1, "user_override", 1.0, False
    db.commit()
    snap = compute_and_store_snapshot(db, user_id)
    return {"flow_id": flow_id, "category": category, "snapshot_id": snap.id}


# ---------------------------------------------------------------------------
# 수입·지출·자산 분석 (1차 기본 분석 화면용)
# ---------------------------------------------------------------------------
def analysis(db: Session, user_id: int) -> dict:
    inp = load_engine_input(db, user_id)
    monthly: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"income": 0.0, "fixed": 0.0, "variable": 0.0, "saving": 0.0})
    for f in inp.flows:
        key = f"{f.occurred_on.year}-{f.occurred_on.month:02d}"
        if f.major == "income":
            monthly[key]["income"] += f.amount
        elif f.major in ("fixed", "variable", "saving"):
            monthly[key][f.major] += f.amount
    months = [{"month": k, **{n: round(v) for n, v in vals.items()},
               "net": round(vals["income"] - vals["fixed"] - vals["variable"])}
              for k, vals in sorted(monthly.items())]

    assets = [h for h in inp.holdings if h.side == "asset"]
    debts = [h for h in inp.holdings if h.side == "liability"]
    comp: Dict[str, float] = defaultdict(float)
    for h in assets:
        comp[h.kind] += h.amount
    snap = latest_snapshot(db, user_id)
    details = json.loads(snap.details_json) if snap else {}
    return {
        "as_of": inp.as_of.isoformat(),
        "monthly": months,
        "asset_composition": {k: round(v) for k, v in comp.items()},
        "assets": [{"name": h.name, "kind": h.kind, "sub": h.sub, "amount": round(h.amount),
                    "source": h.source} for h in sorted(assets, key=lambda h: -h.amount)],
        "liabilities": [{"name": h.name, "kind": h.kind, "sub": h.sub, "amount": round(h.amount)}
                        for h in debts],
        "category_share_pct": details.get("spending", {}).get("category_share_pct", {}),
        "outliers": details.get("spending", {}).get("outliers", []),
    }
