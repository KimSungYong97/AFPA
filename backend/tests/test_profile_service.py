"""금융 프로필 서비스 단위 테스트"""
from app.models.schemas import ProfileInput
from app.services.profile_service import _calc_health_score, _grade


def make_input(**overrides) -> ProfileInput:
    base = dict(
        monthly_income=3_000_000,
        monthly_fixed_expense=1_000_000,
        monthly_variable_expense=800_000,
        deposit=5_000_000,
        savings=3_000_000,
        investment=2_000_000,
        other_assets=0,
        total_debt=0,
    )
    base.update(overrides)
    return ProfileInput(**base)


def test_health_score_range():
    score = _calc_health_score(make_input())
    assert 0 <= score <= 100


def test_health_score_high_for_good_finances():
    """저축률 40%, 부채 0, 비상금 충분 → 높은 점수"""
    score = _calc_health_score(make_input())
    assert score >= 80


def test_health_score_low_for_heavy_debt():
    """부채가 자산을 초과하면 부채 점수(30점)를 잃어 점수가 하락"""
    base_score = _calc_health_score(make_input())
    debt_score = _calc_health_score(make_input(total_debt=50_000_000))
    assert debt_score < base_score
    assert debt_score <= 70


def test_grade():
    assert _grade(85) == "A"
    assert _grade(65) == "B"
    assert _grade(45) == "C"
    assert _grade(25) == "D"
    assert _grade(5) == "E"
