"""분류 확인·수정 API (분류 4단계: 사용자 직접 수정)"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import ClassifiedFlow
from app.models.schemas import FlowOverrideIn, OverrideIn
from app.pipeline.dictionary import ALL_CATEGORIES
from app.services import pipeline_service

router = APIRouter()


@router.get("/categories")
def categories():
    """선택 가능한 카테고리 목록"""
    from app.pipeline.dictionary import FIXED_CATEGORIES, VARIABLE_CATEGORIES
    return {"variable": VARIABLE_CATEGORIES, "fixed": FIXED_CATEGORIES}


@router.get("/{user_id}/review")
def review(user_id: int, db: Session = Depends(get_db)):
    """미분류·낮은 확신 건을 상호 단위로 반환 — 사용자가 한 번에 확정한다"""
    return {"items": pipeline_service.review_items(db, user_id)}


@router.get("/{user_id}/summary")
def summary(user_id: int, db: Session = Depends(get_db)):
    """분류 단계별 확정 비율 (평가 대시보드의 분류 지표)"""
    rows = (db.query(ClassifiedFlow.stage, func.count(ClassifiedFlow.id))
            .filter_by(user_id=user_id).group_by(ClassifiedFlow.stage).all())
    total = sum(c for _, c in rows)
    review = db.query(ClassifiedFlow).filter_by(user_id=user_id, needs_review=True).count()
    return {
        "total": total,
        "by_stage": {int(s): {"count": c, "ratio": round(c / total, 4)} for s, c in rows} if total else {},
        "needs_review": review,
    }


@router.put("/{user_id}/override")
def override(user_id: int, body: OverrideIn, db: Session = Depends(get_db)):
    """가맹점 단위 수정 — 규칙으로 저장되어 이후 동일 상호에 1단계로 즉시 적용된다"""
    if body.category not in ALL_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"알 수 없는 카테고리: {body.category}")
    try:
        return pipeline_service.apply_override(db, user_id, body.merchant, body.category)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.put("/{user_id}/flows/{flow_id}")
def override_flow(user_id: int, flow_id: int, body: FlowOverrideIn, db: Session = Depends(get_db)):
    """한 건 단위 수정 — 가맹점명이 없어 규칙으로 저장할 수 없는 거래용"""
    try:
        return pipeline_service.apply_flow_override(db, user_id, flow_id, body.category)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/{user_id}/flows")
def list_flows(
    user_id: int,
    source: Optional[str] = Query(None, description="bank / card / efin / telecom / insurance / loan / invest / irp"),
    major: Optional[str] = Query(None, description="income / fixed / variable / saving / transfer / ignored"),
    category: Optional[str] = None,
    method: Optional[str] = Query(None, description="llm(AI 추정) / review(확인 필요) / user(사용자 수정) / rule(규칙)"),
    q: Optional[str] = Query(None, description="가게·적요 검색어"),
    month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """입출금·결제 내역과 분류 결과(분류 방법 포함). method=llm 이면 3단계 LLM이 분류한 거래만 본다."""
    qy = db.query(ClassifiedFlow).filter(ClassifiedFlow.user_id == user_id)
    if source:
        qy = qy.filter(ClassifiedFlow.source == source)
    if major:
        qy = qy.filter(ClassifiedFlow.major_class == major)
    if category:
        qy = qy.filter(ClassifiedFlow.category == category)
    if method == "llm":
        qy = qy.filter(ClassifiedFlow.rule.in_(["llm", "llm_cache"]))
    elif method == "review":
        qy = qy.filter(ClassifiedFlow.needs_review.is_(True))
    elif method == "user":
        qy = qy.filter(ClassifiedFlow.rule == "user_override")
    elif method == "rule":
        qy = qy.filter(ClassifiedFlow.rule.notin_(["llm", "llm_cache", "user_override", "unresolved", "no_name"]))
    if q:
        qy = qy.filter(ClassifiedFlow.counterparty.contains(q))
    if month:
        y, m = int(month[:4]), int(month[5:])
        nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
        qy = qy.filter(ClassifiedFlow.occurred_on >= date(y, m, 1), ClassifiedFlow.occurred_on < nxt)
    total = qy.count()
    rows = qy.order_by(ClassifiedFlow.occurred_on.desc(), ClassifiedFlow.id.desc()).offset(offset).limit(limit).all()
    llm_count = db.query(ClassifiedFlow).filter(ClassifiedFlow.user_id == user_id,
                                                ClassifiedFlow.rule.in_(["llm", "llm_cache"])).count()
    return {
        "total": total, "llm_total": llm_count,
        "items": [{
            "id": r.id, "date": r.occurred_on.isoformat(), "amount": r.amount, "direction": r.direction,
            "source": r.source, "counterparty": r.counterparty, "major": r.major_class, "category": r.category,
            "stage": r.stage, "rule": r.rule, "confidence": r.confidence, "needs_review": r.needs_review,
            "recurring": r.is_recurring,
        } for r in rows],
    }
