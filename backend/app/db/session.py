"""DB 세션 관리 (SQLAlchemy)"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """앱 시작 시 테이블 생성 (운영에서는 Alembic 마이그레이션 사용 권장)"""
    from app.models import entities  # noqa: F401 - 모델 등록

    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI 의존성 주입용 DB 세션"""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
