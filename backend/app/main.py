"""AFPA - AI Financial Planning Agent
FastAPI 애플리케이션 진입점
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import profile, goals, market_data, planning, monitoring
from app.db.session import init_db

app = FastAPI(
    title="AI Financial Planning Agent",
    description="목표 기반 금융 의사결정 에이전트 API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: 운영 환경에서는 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(profile.router, prefix="/api/profile", tags=["5.1 금융 프로필"])
app.include_router(goals.router, prefix="/api/goals", tags=["5.2 목표 관리"])
app.include_router(market_data.router, prefix="/api/market", tags=["5.3 금융 정보 수집"])
app.include_router(planning.router, prefix="/api/planning", tags=["5.4/5.7/5.8 Planning Agent"])
app.include_router(monitoring.router, prefix="/api/monitoring", tags=["5.5/5.6 모니터링"])


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health_check():
    return {"status": "ok"}
