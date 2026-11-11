"""가상 사용자 + 가상 마이데이터 → 1차 파이프라인 실행 스크립트

사용법:
    cd backend
    python -m scripts.generate_mydata        # 1) 페르소나 → 마이데이터 규격 JSON 생성 (data/mydata/)
    python -m scripts.seed_data --reset      # 2) 사용자·온보딩·동의 등록 → 분류 → 프로필 스냅샷
    python -m scripts.seed_data --reset --llm   #    3단계 LLM 분류 사용 (OPENAI_API_KEY 필요)

파이프라인:
    personas.json ─ generate_mydata ─▶ data/mydata/user_XXX/*.json (마이데이터 규격)
    data/onboarding.json (온보딩 입력) ┐
                                       ├▶ 동의 기록 → 자동 분류(4단계) → 6개 엔진 → financial_snapshots
    data/mydata/user_XXX/*.json ───────┘                      └▶ 기존 FinancialProfile/Transaction 브리지
"""
import json
import sys
from datetime import date
from pathlib import Path

from app.db.session import Base, SessionLocal, engine, init_db
from app.models.entities import AccountHolding, Goal, User
from app.models.schemas import OnboardingInput
from app.pipeline.mydata_source import MYDATA_DIR, load_user_data
from app.services import onboarding_service, pipeline_service

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PERSONA_FILE = DATA_DIR / "personas.json"
ONBOARDING_FILE = DATA_DIR / "onboarding.json"


def _verify_holdings(db, user_id: int, persona: dict) -> None:
    """분류된 자산·부채 합계가 페르소나 정의(생성 시 기준값)와 일치하는지 검증"""
    rows = db.query(AccountHolding).filter_by(user_id=user_id).all()
    cash = sum(r.amount for r in rows if r.side == "asset" and r.kind == "cash")
    time_dep = sum(r.amount for r in rows if r.kind == "savings" and r.sub == "정기예금")
    savings = sum(r.amount for r in rows if r.kind == "savings" and r.sub in ("적금", "청약"))
    invest = sum(r.amount for r in rows if r.kind == "invest")
    pension = sum(r.amount for r in rows if r.kind == "pension")
    debt = sum(r.amount for r in rows if r.side == "liability")
    src = persona["profile"]
    checks = {
        "deposit": (cash + time_dep, src["deposit"]), "savings": (savings, src["savings"]),
        "investment": (invest, src["investment"]), "other_assets": (pension, src["other_assets"]),
        "total_debt": (debt, src["total_debt"]),
    }
    for key, (got, want) in checks.items():
        if abs(got - want) > 1:
            raise ValueError(f"[user {user_id}] {key} 불일치: 분류 결과={got:,.0f} vs 페르소나={want:,.0f}")


def seed(reset: bool = False, use_llm: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(bind=engine)
        print("기존 테이블 삭제 완료")
    init_db()

    personas = {p["id"]: p for p in json.load(open(PERSONA_FILE, encoding="utf-8"))}
    onboarding = json.load(open(ONBOARDING_FILE, encoding="utf-8"))

    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            print("이미 데이터가 존재합니다. --reset 옵션으로 초기화 후 재적재하세요.")
            return
        if not MYDATA_DIR.exists():
            raise FileNotFoundError("data/mydata 가 없습니다. 먼저 `python -m scripts.generate_mydata` 를 실행하세요.")

        for user_dir in sorted(MYDATA_DIR.glob("user_*")):
            meta = json.load(open(user_dir / "_user.json", encoding="utf-8"))
            uid = meta["user_id"]

            db.add(User(id=uid, name=meta["name"], job=meta.get("job"),
                        persona_type=meta.get("persona_type"), description=meta.get("description")))
            db.flush()
            for g in meta.get("goals", []):
                db.add(Goal(user_id=uid, name=g["name"], goal_type=g["goal_type"],
                            target_amount=g["target_amount"], current_amount=g["current_amount"],
                            target_date=date.fromisoformat(g["target_date"]) if g.get("target_date") else None,
                            priority=g["priority"]))
            db.commit()

            onboarding_service.upsert(db, uid, OnboardingInput(**onboarding[str(uid)]))
            pipeline_service.record_consent(db, uid)
            result = pipeline_service.sync_user(db, uid, load_user_data(user_dir), use_llm=use_llm)
            _verify_holdings(db, uid, personas[uid])

            snap = pipeline_service.latest_snapshot(db, uid)
            print(f"[{meta['name']}] 거래 {result['flows']}건 분류 (단계별 {result['by_stage']}, "
                  f"확인 필요 {result['needs_review']}건) / 건강도 {snap.health_score} "
                  f"잠재력 {snap.potential_score} 월 여유 자금 {snap.net_cash_flow:,.0f}")

        print("\n정합성 검증 통과 (분류된 자산·부채 합계 == 페르소나 정의)")
        print("✅ 가상 사용자 → 분류 → 프로필 스냅샷 완료")
    finally:
        db.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    seed(reset="--reset" in sys.argv, use_llm="--llm" in sys.argv)
