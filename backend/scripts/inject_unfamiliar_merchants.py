"""가상 카드 승인내역 일부를 '사전에 없는 낯선 가게 이름'으로 바꾼다 (3단계 LLM 분류 시연·평가용)

기본 테스트 데이터의 가맹점은 모두 사전에 시드되어 있어 LLM 단계(3단계)가 한 번도 쓰이지 않는다.
이 스크립트는 사용자별로 승인내역 몇 건의 가맹점명만 바꾼다(금액·일시·정답 카테고리는 그대로).
- 정답 라벨(_category)과 원래 이름(_original_name)을 남겨 두므로 평가에 쓸 수 있다
- 금액·카테고리가 같아 월 소비 합계는 변하지 않는다
- 여러 달에 걸쳐 같은 가게가 반복되도록 해서 LLM 결과 캐시도 확인할 수 있다
- 이미 적용된 파일은 건드리지 않는다(멱등)

사용법:  cd backend && python -m scripts.inject_unfamiliar_merchants
(scripts.generate_mydata 로 데이터를 새로 만든 뒤에도 한 번 실행한다)
"""
import json
import random
import sys

from app.pipeline.mydata_source import MYDATA_DIR

# 가게 이름(사전·키워드에 없음) → 정답 카테고리. LLM이 알 만한 이름과 알기 어려운 이름을 섞었다.
UNFAMILIAR = [
    ("봄날 곱창", "식비"),
    ("주식회사 케이엔제이", "식비"),           # 설계 문서의 예시 — 이름만으로는 알 수 없음
    ("리틀포레스트 베이커", "카페/간식"),
    ("에이치앤엠 코리아", "쇼핑"),
    ("하루 요가원", "문화/여가"),
    ("서울아산 소아과", "의료/건강"),
]
PER_USER = 4          # 사용자당 바꿀 가게 수
TX_PER_MERCHANT = 3   # 가게당 바꿀 승인 건수 (서로 다른 달)


def inject(user_dir) -> int:
    path = user_dir / "card_approvals.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["approved_list"]
    if any("_original_name" in r for r in rows):
        return 0

    uid = int(user_dir.name.split("_")[1])
    rng = random.Random(1000 + uid)                      # 전역 난수와 분리해 기존 데이터를 흔들지 않는다
    picks = rng.sample(UNFAMILIAR, PER_USER)
    changed = 0
    for name, category in picks:
        pool = [r for r in rows if r.get("_category") == category and not r.get("_is_fixed")
                and r.get("status") == "01" and "_original_name" not in r]
        by_month = {}
        for r in pool:
            by_month.setdefault(r["approved_dtime"][:6], []).append(r)
        months = sorted(by_month)
        for month in rng.sample(months, min(TX_PER_MERCHANT, len(months))):
            r = rng.choice(by_month[month])
            r["_original_name"] = r["merchant_name"]
            r["merchant_name"] = name
            changed += 1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def main() -> None:
    total = 0
    for user_dir in sorted(MYDATA_DIR.glob("user_*")):
        n = inject(user_dir)
        total += n
        print(f"{user_dir.name}: {n}건 변경" if n else f"{user_dir.name}: 이미 적용됨")
    print(f"합계 {total}건")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
