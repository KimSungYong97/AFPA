"""5대분류 자동 분류 (합성 마이데이터 응답)"""
from app.pipeline.classifier import classify_flows, classify_holdings
from app.pipeline.merchant import MerchantClassifier


def _bank(trans):
    return {"bank_transactions": {"trans_list": trans}}


def _tx(dtime, ttype, tclass, amt, memo):
    return {"trans_dtime": dtime, "trans_type": ttype, "trans_class": tclass,
            "trans_amt": amt, "trans_memo": memo}


def test_bank_flows_split_income_fixed_saving_transfer():
    trans = []
    for m in ("03", "04", "05", "06"):
        trans += [
            _tx(f"2026{m}25090000", "03", "급여", 3_000_000, "(주)회사 급여"),
            _tx(f"2026{m}25100000", "04", "출금", 600_000, "월세/관리비 이체"),
            _tx(f"2026{m}14110000", "04", "출금", 900_000, "AFPA카드 대금"),
            _tx(f"2026{m}01080000", "07", "대체", 500_000, "적금 자동이체"),
            _tx(f"2026{m}20100000", "04", "출금", 120_000, "생명보험 자동납부"),
        ]
    flows, report = classify_flows(_bank(trans), MerchantClassifier())
    by = {}
    for f in flows:
        by.setdefault((f.major, f.category), []).append(f)

    salary = by[("income", "근로수입")]
    assert len(salary) == 4 and all(f.recurring for f in salary)
    assert all(f.major == "fixed" and f.category == "주거" for f in by[("fixed", "주거")])
    # 카드대금은 카드 승인내역과 이중 집계되지 않도록 지출에서 제외
    assert ("transfer", "카드대금") in by and not any(f.major in ("fixed", "variable") and f.category == "카드대금"
                                                       for f in flows)
    assert len(by[("saving", "저축·투자")]) == 4                       # 지출이 아닌 저축·투자 납입
    assert all(f.major == "ignored" for f in by[("ignored", "전용API중복")])  # 보험은 전용 API로 집계


def test_irregular_deposit_without_keyword_is_irregular_income():
    trans = [_tx("20260305100000", "01", "입금", 80_000, "중고거래"),
             _tx("20260412100000", "01", "입금", 45_000, "용돈")]
    flows, _ = classify_flows(_bank(trans), MerchantClassifier())
    assert [f.category for f in flows] == ["비정기수입", "비정기수입"]
    assert not any(f.recurring for f in flows)


def test_card_subscription_detected_as_fixed_and_cancelled_ignored():
    approvals = [
        {"approved_num": f"A{m}", "approved_dtime": f"2026{m}1009000", "status": "01",
         "merchant_name": "넷플릭스", "approved_amt": 17000} for m in ("03", "04", "05")
    ]
    approvals.append({"approved_num": "X", "approved_dtime": "20260507090000", "status": "02",
                      "merchant_name": "스타벅스 역삼점", "approved_amt": 5000})   # 취소 건
    approvals.append({"approved_num": "Y", "approved_dtime": "20260508090000", "status": "01",
                      "merchant_name": "스타벅스 역삼점", "approved_amt": 5000})
    flows, _ = classify_flows({"card_approvals": {"approved_list": approvals}}, MerchantClassifier())
    assert len(flows) == 4
    netflix = [f for f in flows if f.counterparty == "넷플릭스"]
    assert all(f.major == "fixed" for f in netflix)
    assert [f.major for f in flows if "스타벅스" in f.counterparty] == ["variable"]


def test_same_merchant_monthly_charge_becomes_fixed_by_recurrence():
    """사전 카테고리가 변동(교통)이어도 3회 이상 같은 날·같은 금액이면 고정지출로 승격"""
    approvals = [{"approved_num": f"T{m}", "approved_dtime": f"2026{m}0508000", "status": "01",
                  "merchant_name": "서울교통공사", "approved_amt": 55000} for m in ("03", "04", "05", "06")]
    flows, _ = classify_flows({"card_approvals": {"approved_list": approvals}}, MerchantClassifier())
    assert all(f.major == "fixed" and f.category == "교통" for f in flows)


def test_unknown_and_nameless_merchants_are_flagged_for_review():
    approvals = [
        {"approved_num": "1", "approved_dtime": "20260305100000", "status": "01",
         "merchant_name": "주식회사 케이엔제이", "approved_amt": 30000},
        {"approved_num": "2", "approved_dtime": "20260306100000", "status": "01",
         "merchant_name": None, "approved_amt": 12000},
    ]
    flows, report = classify_flows({"card_approvals": {"approved_list": approvals}}, MerchantClassifier())
    assert [f.stage for f in flows] == [4, 0]
    assert report.needs_review == 2 and all(f.category == "미분류" for f in flows)


def test_holdings_classified_by_account_type_code():
    data = {
        "bank_accounts": {
            "account_list": [
                {"account_num": "1", "account_type": "1001", "prod_name": "자유입출금"},
                {"account_num": "2", "account_type": "1002", "prod_name": "정기예금"},
                {"account_num": "3", "account_type": "1003", "prod_name": "청년적금"},
                {"account_num": "4", "account_type": "9999", "prod_name": "CMA 통장"},   # 코드 모호 → 상품명 보조
                {"account_num": "5", "account_type": "1001", "prod_name": "외화통장", "is_foreign_deposit": True},
            ],
            "detail_list": [{"account_num": str(i), "balance_amt": a}
                            for i, a in zip(range(1, 6), (1_000, 2_000, 3_000, 4_000, 5_000))],
        },
        "efin_accounts": {"balance_list": [{"account_id": "PAY", "balance_amt": 700}]},
        "invest_accounts": {"basic_list": [{"account_num": "I", "withholdings_amt": 100}],
                            "product_list": [{"prod_type": "401", "prod_name": "ETF", "eval_amt": 900},
                                             {"prod_type": "301", "prod_name": "펀드", "eval_amt": 800}]},
        "irp_accounts": {"detail_list": [{"irp_prod_name": "IRP", "eval_amt": 600}]},
        "bank_loans": {"loan_list": [{"account_num": "L", "account_type": "3170", "prod_name": "전세자금대출"}],
                       "detail_list": [{"account_num": "L", "balance_amt": 50_000}]},
        "card_loans": {"revolving_list": [{"remain_amt": 400}]},
    }
    holdings = classify_holdings(data)
    by_name = {x.name: x for x in holdings}
    h = {(x.side, x.kind, x.sub): x for x in holdings if x.name != "외화통장"}
    assert by_name["자유입출금"].emergency_eligible is True
    assert h[("asset", "savings", "정기예금")].amount == 2_000
    assert h[("asset", "savings", "적금")].amount == 3_000
    assert h[("asset", "cash", "CMA")].emergency_eligible is True
    # D-06: 페이머니·외화는 비상금에서 제외
    assert h[("asset", "cash", "페이머니")].emergency_eligible is False
    assert by_name["외화통장"].emergency_eligible is False
    assert h[("asset", "invest", "주식/ETF")].amount == 900 and h[("asset", "invest", "펀드")].amount == 800
    assert h[("asset", "pension", "IRP")].amount == 600
    assert h[("liability", "secured", "전세자금대출")].amount == 50_000
    assert h[("liability", "other", "리볼빙")].amount == 400
