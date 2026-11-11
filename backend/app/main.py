"""AFPA - AI Financial Planning Agent
FastAPI 애플리케이션 진입점
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    agent, classification, goals, market_data, monitoring, mydata, onboarding, planner, planning, profile, users,
)
from app.db.session import init_db

app = FastAPI(
    title="AI Financial Planning Agent",
    description="목표 기반 금융 의사결정 에이전트 API",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: 운영 환경에서는 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
# 1차: 기본 플랫폼
app.include_router(users.router, prefix="/api/users", tags=["1차 사용자"])
app.include_router(onboarding.router, prefix="/api/onboarding", tags=["1차 온보딩"])
app.include_router(mydata.router, prefix="/api/mydata", tags=["1차 마이데이터 연동"])
app.include_router(classification.router, prefix="/api/classification", tags=["1차 자동 분류"])
app.include_router(profile.router, prefix="/api/profile", tags=["1차 금융 프로필"])
app.include_router(goals.router, prefix="/api/goals", tags=["1차 목표 관리"])
# 2차: 통합 플래너
app.include_router(planner.router, prefix="/api/planner", tags=["2차 통합 플래너"])
app.include_router(agent.router, prefix="/api/agent", tags=["변화 감시 에이전트"])
# 프로토타입 (새 설계상 2차 이후 기능, 통합 플래너로 대체 예정)
app.include_router(market_data.router, prefix="/api/market", tags=["금융 정보 수집 (프로토타입)"])
app.include_router(planning.router, prefix="/api/planning", tags=["Planning Agent (프로토타입)"])
app.include_router(monitoring.router, prefix="/api/monitoring", tags=["모니터링 (프로토타입)"])


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health_check():
    return {"status": "ok"}
