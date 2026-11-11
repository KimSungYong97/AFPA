"""가상 마이데이터 3명 전체 파이프라인 — 평가 기준 초기 목표 검증

「평가 기준 및 성능 대시보드」: 변동지출 카테고리 90%+, 고정지출 정밀도 90%+, 정기수입 재현율 95%+
(정답 라벨은 평가에만 사용하고 분류 입력에는 쓰지 않는다)
"""
import pytest

from app.pipeline.mydata_source import MYDATA_DIR
from scripts.evaluate_classification import evaluate_user

USERS = sorted(MYDATA_DIR.glob("user_*"))


@pytest.fixture(scope="module")
def results():
    return {p.name: evaluate_user(p) for p in USERS}


def test_three_virtual_users_exist():
    assert [p.name for p in USERS] == ["user_001", "user_002", "user_003"]


def test_classification_meets_initial_targets(results):
    for name, r in results.items():
        assert r["category_acc"] >= 0.90, name
        assert r["fixed_precision"] >= 0.90, name
        assert r["income_recurring"] == r["income_flows"], name      # 정기수입 재현율


def test_amounts_match_persona_definition(results):
    for r in results.values():
        assert r["income"] == r["income_label"]
        assert r["variable"] == pytest.approx(r["variable_label"], rel=0.08)   # 페이 결제 등 소폭 차이
        assert r["fixed"] >= r["fixed_label"]            # 정의값(주거·공과금·보험·통신) + 대출 원리금


def test_persona_contrast_shows_in_scores(results):
    r1, r2, r3 = (results[f"user_00{i}"] for i in (1, 2, 3))
    assert r3["net_cash_flow"] < 0 < r1["net_cash_flow"]            # 과소비형은 마이너스 현금흐름
    assert r3["health"] < r1["health"] and r3["health"] < r2["health"]
    assert r2["net_worth"] < 0                                       # 전세대출 1.2억 보유
    assert r2["dsr"] > r1["dsr"]
    assert r1["potential"] > r3["potential"]                         # 사회초년생: 건강도보다 잠재력이 두드러짐
