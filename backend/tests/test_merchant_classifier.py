"""가맹점 분류 4단계 + 정규화"""
from app.pipeline.dictionary import UNCLASSIFIED
from app.pipeline.merchant import MerchantClassifier
from app.pipeline.text import normalize_merchant


def test_normalize_strips_branch_corp_and_parens():
    assert normalize_merchant("스타벅스 역삼점") == "스타벅스"
    assert normalize_merchant("(주)케이엔제이") == "케이엔제이"
    assert normalize_merchant("주식회사 케이엔제이") == "케이엔제이"
    assert normalize_merchant("GS25 서초점 (본점)") == "gs25"
    assert normalize_merchant("") == ""
    # 상호 자체가 '점'으로 끝나는 단일 토큰은 건드리지 않는다
    assert normalize_merchant("편의점") == "편의점"


def test_stage0_no_merchant_name():
    r = MerchantClassifier().classify(None)
    assert (r.stage, r.category, r.needs_review) == (0, UNCLASSIFIED, True)
    assert MerchantClassifier().classify("   ").stage == 0


def test_stage1_exact_match_ignores_branch():
    r = MerchantClassifier().classify("스타벅스 강남점")
    assert (r.stage, r.category, r.needs_review) == (1, "카페/간식", False)


def test_stage1_user_override_beats_dictionary():
    r = MerchantClassifier(overrides={"스타벅스": "식비"}).classify("스타벅스 역삼점")
    assert (r.stage, r.category, r.rule) == (1, "식비", "user_override")


def test_stage2_brand_token_and_keyword():
    mc = MerchantClassifier()
    assert mc.classify("CGV 강남").category == "문화/여가"          # 첫 단어가 사전 상호
    r = mc.classify("행복동물병원")                                  # 사전에 없는 상호 → 키워드 '병원'
    assert (r.stage, r.category) == (2, "의료/건강")


def test_stage2_longest_keyword_wins():
    # '쿠팡'(쇼핑)보다 '쿠팡와우'(구독서비스)가 우선해야 한다
    assert MerchantClassifier().classify("쿠팡와우 월회비").category == "구독서비스"


def test_stage3_llm_result_is_applied_but_flagged_and_cached():
    calls = []

    def fake_llm(name):
        calls.append(name)
        return "교통"

    mc = MerchantClassifier(llm=fake_llm)
    r1 = mc.classify("주식회사 케이엔제이")
    assert (r1.stage, r1.category, r1.needs_review) == (3, "교통", True)
    assert mc.new_candidates == {"케이엔제이": "교통"}     # 사전 자동 편입 없이 후보로만 저장
    r2 = mc.classify("(주)케이엔제이")                     # 정규화 키로 캐시 적중 → LLM 재호출 없음
    assert r2.rule == "llm_cache" and len(calls) == 1


def test_stage3_invalid_or_failed_llm_falls_back_to_stage4():
    assert MerchantClassifier(llm=lambda n: "엉뚱한분류").classify("케이엔제이").stage == 4

    def boom(_):
        raise RuntimeError("api down")

    r = MerchantClassifier(llm=boom).classify("케이엔제이")
    assert (r.stage, r.category, r.needs_review) == (4, UNCLASSIFIED, True)


def test_no_llm_unknown_merchant_goes_to_user_review():
    r = MerchantClassifier().classify("주식회사 케이엔제이")
    assert (r.stage, r.category, r.needs_review) == (4, UNCLASSIFIED, True)
