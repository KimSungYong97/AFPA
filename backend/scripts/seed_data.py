"""마이데이터 원천 JSON → DB 적재 스크립트

사용법:
    cd backend
    python -m scripts.generate_mydata        # 1) 마이데이터 규격 JSON 생성 (data/mydata/)
    python -m scripts.seed_data              # 2) 어댑터로 변환하여 DB 적재
    python -m scripts.seed_data --reset      #    DB 초기화 후 적재

파이프라인:
    personas.json → generate_mydata → data/mydata/user_XXX/*.json (마이데이터 규격)
                                            ↓
                            mydata_adapter (변환 + 정합성 검증)
                                            ↓
                            DB (User/FinancialProfile/Goal/Transaction)
"""
import json
import sys
from datetime import date
from pathlib import Path

from app.db.session import Base, SessionLocal, engine, init_db
from app.models.entities import FinancialProfile, Goal, Transaction, User
from app.models.schemas import ProfileInput
from app.services.profile_service import _calc_health_score
from scripts import mydata_adapter

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PERSONA_FILE = DATA_DIR / "personas.json"


def _verify_against_personas(converted: list) -> None:
    """어댑터 변환 결과가 personas.json 원본 총액과 일치하는지 검증"""
    with open(PERSONA_FILE, encoding="utf-8") as f:
        personas = {p["id"]: p for p in json.load(f)}

    for item in converted:
        uid = item["user"]["id"]
        src = personas[uid]["profile"]
        dst = item["profile"]
        for key in ["deposit", "savings", "investment", "other_assets", "total_debt"]:
            if abs(src[key] - dst[key]) > 1:
                raise ValueError(
                    f"[user {uid}] {key} 불일치: personas={src[key]:,} vs mydata={dst[key]:,}"
                )
    print("정합성 검증 통과 (personas.json == mydata 변환 결과)")


def seed(reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(bind=engine)
        print("기존 테이블 삭제 완료")

    init_db()
    db = SessionLocal()

    try:
        if db.query(User).count() > 0:
            print("이미 데이터가 존재합니다. --reset 옵션으로 초기화 후 재적재하세요.")
            return

        converted = mydata_adapter.convert_all()
        _verify_against_personas(converted)

        goal_id = 0
        for item in converted:
            u = item["user"]
            db.add(User(**u))

            pdata = ProfileInput(**item["profile"])
            db.add(FinancialProfile(
                user_id=u["id"], **item["profile"],
                health_score=_calc_health_score(pdata),
            ))

            for g in item["goals"]:
                goal_id += 1
                db.add(Goal(
                    id=goal_id, user_id=u["id"],
                    name=g["name"], goal_type=g["goal_type"],
                    target_amount=g["target_amount"], current_amount=g["current_amount"],
                    target_date=date.fromisoformat(g["target_date"]) if g.get("target_date") else None,
                    priority=g["priority"],
                ))

            for t in item["transactions"]:
                db.add(Transaction(**t))

            print(f"[{u['name']}] 프로필 1건, 목표 {len(item['goals'])}건, "
                  f"거래 {len(item['transactions'])}건 적재")

        db.commit()
        print("\n✅ 마이데이터 → DB 적재 완료!")
        _print_summary(db)
    finally:
        db.close()


def _print_summary(db) -> None:
    print("\n--- 요약 ---")
    print(f"사용자      : {db.query(User).count()}명")
    print(f"금융 프로필 : {db.query(FinancialProfile).count()}건")
    print(f"목표        : {db.query(Goal).count()}건")
    print(f"거래내역    : {db.query(Transaction).count()}건")


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
