"""마이데이터 표준 API 규격 기반 테스트 데이터 생성기

금융분야 마이데이터 표준 API 규격(v202102-1)의 업권별 정보제공 API 응답 형식으로
페르소나별 원천 데이터(JSON)를 생성한다.

사용법:
    cd backend
    python -m scripts.generate_mydata

입력:  data/personas.json  (인물 설정 — 자산/부채/소비 규모)
출력:  data/mydata/user_{id:03d}/*.json  (업권별 API 응답 형식)

생성 파일 (업권 9종):
    bank_accounts.json        은행-001/002/003  계좌목록 + 수신계좌 기본/추가정보
    bank_transactions.json    은행-004          수신계좌 거래내역 (6개월)
    bank_loans.json           은행-008/009/010  대출상품계좌 기본/추가/거래내역
    card_list.json            카드-001/002      카드 목록/기본정보
    card_points.json          카드-003          포인트 정보
    card_bills.json           카드-004/005      청구 기본/추가정보
    card_approvals.json       카드-007/008      국내/해외 승인내역 (6개월)
    card_loans.json           카드-009~012      카드 대출 (리볼빙/단기/장기)
    invest_accounts.json      금투-001~004      계좌목록/기본정보/거래내역/상품정보
    insurance_list.json       보험-001~005      보험목록/기본/특약/자동차/납입정보
    efin_accounts.json        전금-001~005      전자지급수단/잔액/충전/결제내역
    telecom_contracts.json    통신-001~004      계약목록/청구/결제내역
    irp_accounts.json         IRP-001~004       IRP 계좌/기본/추가/거래내역
    capital_loans.json        할부금융-001~006   할부/리스
    ginsu_insurances.json     보증보험-001~003   보증보험 증권/기본/납입

정합성 규칙:
    - 은행 수신잔액 합계 == persona.profile.deposit + savings
    - 금투 평가금액 + IRP == persona.profile.investment + other_assets
    - 대출 잔액 합계(은행+카드+할부금융) == persona.profile.total_debt
    - 카드 승인내역 월 합계 ≈ persona.monthly_spending (변동지출)
    - 이번 달 승인내역은 current_month_factor 배율 (5.5 모니터링 테스트)
"""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PERSONA_FILE = DATA_DIR / "personas.json"
MYDATA_DIR = DATA_DIR / "mydata"

# ---------------------------------------------------------------------------
# 공통 코드/유틸
# ---------------------------------------------------------------------------
ORG_BANK = {"code": "020", "name": "AFPA은행"}
ORG_CARD = {"code": "301", "name": "AFPA카드"}
ORG_INVEST = {"code": "247", "name": "AFPA증권"}
ORG_INSU = {"code": "452", "name": "AFPA생명"}
ORG_EFIN = {"code": "901", "name": "AFPA페이"}
ORG_TELECOM = {"code": "T01", "name": "AFPA텔레콤"}
ORG_CAPITAL = {"code": "550", "name": "AFPA캐피탈"}
ORG_GINSU = {"code": "560", "name": "서울보증보험"}

# 변동지출 카테고리 → (비중, 가맹점 목록, 업종코드)
CATEGORY_MERCHANTS = {
    "식비":     (0.35, ["김밥천국 역삼점", "맘스터치 강남점", "배달의민족", "GS25 서초점", "이마트 성수점"], "5812"),
    "쇼핑":     (0.20, ["쿠팡", "무신사", "올리브영 강남점", "네이버쇼핑", "다이소 역삼점"], "5311"),
    "교통":     (0.10, ["카카오T", "코레일", "서울교통공사", "GS칼텍스 서초주유소"], "4121"),
    "문화/여가": (0.15, ["CGV 강남", "교보문고 광화문점", "인터파크티켓", "볼링클럽 서초"], "7832"),
    "카페/간식": (0.10, ["스타벅스 역삼점", "메가커피 서초점", "투썸플레이스", "배스킨라빈스"], "5814"),
    "의료/건강": (0.05, ["서초튼튼약국", "강남정형외과", "GNC 건강식품"], "8011"),
    "기타":     (0.05, ["CU 편의점", "세탁특공대", "미용실 준오헤어"], "5999"),
}

SUBSCRIPTION_MERCHANTS = ["넷플릭스", "유튜브프리미엄", "멜론", "쿠팡와우"]


def _dt(ts: datetime) -> str:
    """마이데이터 거래일시 형식 (yyyyMMddHHmmss)"""
    return ts.strftime("%Y%m%d%H%M%S")


def _d(ts: datetime) -> str:
    """마이데이터 일자 형식 (yyyyMMdd)"""
    return ts.strftime("%Y%m%d")


def _month_starts(now: datetime, months: int = 6) -> list:
    """이번 달 포함 최근 N개월의 (월 시작일, 해당월 마지막 생성일) 목록 (과거→현재)"""
    result = []
    cur = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for i in range(months - 1, -1, -1):
        ms = cur
        for _ in range(i):
            ms = (ms - timedelta(days=1)).replace(day=1)
        max_day = now.day if ms.month == now.month and ms.year == now.year else 28
        result.append((ms, max_day))
    return result


def _resp(payload: dict) -> dict:
    """표준 응답 래퍼 (rsp_code/rsp_msg + payload)"""
    return {"rsp_code": "00000", "rsp_msg": "성공", "search_timestamp": _dt(datetime.utcnow()), **payload}


# ---------------------------------------------------------------------------
# 페르소나별 자산/부채 배분 설계
#   personas.json의 총액을 업권별 계좌로 쪼갠다 (id 기준 하드코딩된 배분 비율)
# ---------------------------------------------------------------------------
def _allocate(spec: dict) -> dict:
    """페르소나 → 업권별 배분 명세"""
    p = spec["profile"]
    uid = spec["id"]

    alloc = {
        "checking": 0.0,      # 입출금
        "deposit": 0.0,       # 정기예금
        "savings": p["savings"],   # 적금
        "invest": 0.0,        # 금투
        "irp": 0.0,           # IRP
        "bank_loan": 0.0,     # 은행 대출
        "card_revolving": 0.0,
        "card_short_loan": 0.0,
        "capital_loan": 0.0,
        "efin_balance": 0.0,  # 페이 선불 잔액 (checking에서 분리)
        "has_car_insu": False,
        "has_ginsu": False,   # 전세보증보험
        "cards": 1,
    }

    if uid == 1:  # 김철수 — 사회초년생
        alloc.update({
            "checking": 2_800_000, "deposit": 5_000_000, "efin_balance": 200_000,
            "invest": p["investment"],  # 3,000,000 금투
            "has_ginsu": True,          # 전세보증 (전세보증금 목표와 연결)
            "cards": 1,
        })
    elif uid == 2:  # 이영희 — 신혼부부
        alloc.update({
            "checking": 4_700_000, "deposit": 10_000_000, "efin_balance": 300_000,
            "invest": p["investment"],           # 25,000,000 금투
            "irp": p["other_assets"],            # 5,000,000 IRP
            "bank_loan": p["total_debt"],        # 120,000,000 전세대출
            "has_car_insu": True,
            "cards": 2,
        })
    elif uid == 3:  # 박과소 — 과소비형
        alloc.update({
            "checking": 1_400_000, "deposit": 0, "efin_balance": 100_000,
            "invest": p["investment"],           # 500,000
            "card_revolving": 2_000_000,
            "card_short_loan": 3_000_000,
            "capital_loan": 3_000_000,           # 합계 8,000,000 == total_debt
            "cards": 3,
        })
    else:  # 신규 페르소나 기본 배분: 입출금 30% / 예금 70%, 부채는 은행대출
        alloc.update({
            "checking": round(p["deposit"] * 0.3),
            "deposit": round(p["deposit"] * 0.7),
            "invest": p["investment"],
            "irp": p["other_assets"],
            "bank_loan": p["total_debt"],
        })

    # checking + deposit + efin == persona.deposit 검증 보정
    diff = p["deposit"] - (alloc["checking"] + alloc["deposit"] + alloc["efin_balance"])
    alloc["checking"] += diff
    return alloc


# ---------------------------------------------------------------------------
# 은행 (은행-001 ~ 010)
# ---------------------------------------------------------------------------
def gen_bank_accounts(spec: dict, alloc: dict, now: datetime) -> dict:
    uid = spec["id"]
    accounts, basics, details = [], [], []

    def add(num_suffix, prod_name, acc_type, balance, intr=0.0, exp=None, monthly=None):
        account_num = f"110{uid:03d}{num_suffix}"
        accounts.append({
            "account_num": account_num, "is_consent": True, "seqno": "1",
            "prod_name": prod_name, "account_type": acc_type,
            "account_status": "01",  # 활동
            "is_foreign_deposit": False, "is_minus": False,
        })
        basics.append({
            "account_num": account_num, "seqno": "1", "currency_code": "KRW",
            "prod_name": prod_name, "account_type": acc_type,
            "issue_date": "20230115" if uid != 3 else "20240601",
            "exp_date": exp, "commit_amt": None, "monthly_paid_in_amt": monthly,
        })
        details.append({
            "account_num": account_num, "seqno": "1", "currency_code": "KRW",
            "balance_amt": balance, "withdrawable_amt": balance if acc_type == "1001" else 0,
            "offered_rate": intr, "last_paid_in_cnt": None,
        })

    add("0001", "AFPA 자유입출금통장", "1001", alloc["checking"], 0.1)
    if alloc["deposit"] > 0:
        add("0002", "AFPA 정기예금", "1002", alloc["deposit"], 3.2, _d(now + timedelta(days=365)))
    if alloc["savings"] > 0:
        monthly = 500_000 if uid == 1 else 1_000_000
        add("0003", "AFPA 청년적금" if uid == 1 else "AFPA 자유적금", "1003",
            alloc["savings"], 4.5, _d(now + timedelta(days=540)), monthly)

    return _resp({
        "account_cnt": len(accounts), "account_list": accounts,
        "basic_list": basics, "detail_list": details,
    })


def gen_bank_transactions(spec: dict, alloc: dict, now: datetime) -> dict:
    """입출금통장 거래내역 — 급여 입금, 고정지출 출금, 카드대금 출금"""
    uid = spec["id"]
    p = spec["profile"]
    account_num = f"110{uid:03d}0001"
    fixed = p["monthly_fixed_expense"]
    trans = []
    balance = alloc["checking"] + 3_000_000  # 역산용 시작 잔액

    for ms, _max_day in _month_starts(now):
        rows = []
        # 급여 입금 (25일)
        if ms.replace(day=25) <= now:
            rows.append((ms.replace(day=25, hour=9), "03", "급여", p["monthly_income"], "AFPA(주) 급여"))
        # 주거비 이체 (25일)
        if ms.replace(day=25) <= now:
            rows.append((ms.replace(day=25, hour=10), "04", "출금", -round(fixed * 0.55, -2), "월세/관리비 이체"))
        # 공과금 (26일)
        if ms.replace(day=26) <= now:
            rows.append((ms.replace(day=26, hour=14), "04", "출금", -round(fixed * 0.10, -2), "전기/가스/수도"))
        # 카드대금 (14일)
        if ms.replace(day=14) <= now:
            rows.append((ms.replace(day=14, hour=11), "04", "출금", -round(spec["monthly_spending"], -2), "AFPA카드 대금"))
        # 적금 자동이체 (1일)
        if alloc["savings"] > 0:
            monthly = 500_000 if uid == 1 else 1_000_000
            rows.append((ms.replace(day=1, hour=8), "07", "대체", -monthly, "적금 자동이체"))

        for ts, ttype, tclass, amt, memo in rows:
            balance += amt
            trans.append({
                "trans_dtime": _dt(ts), "trans_no": f"T{_dt(ts)}{uid}",
                "trans_type": ttype, "trans_class": tclass, "trans_amt": abs(amt),
                "balance_amt": max(balance, 0), "currency_code": "KRW", "trans_memo": memo,
            })

    return _resp({"account_num": account_num, "trans_cnt": len(trans), "trans_list": trans})


def gen_bank_loans(spec: dict, alloc: dict, now: datetime) -> dict:
    loans, basics, details, trans = [], [], [], []
    uid = spec["id"]

    if alloc["bank_loan"] > 0:
        account_num = f"210{uid:03d}0001"
        loans.append({
            "account_num": account_num, "is_consent": True, "seqno": "1",
            "prod_name": "AFPA 전세자금대출", "account_type": "3170", "account_status": "01",
        })
        basics.append({
            "account_num": account_num, "seqno": "1", "currency_code": "KRW",
            "issue_date": "20240301", "exp_date": _d(now + timedelta(days=365 * 2)),
            "last_offered_rate": 3.8, "repay_date": "25",
            "repay_method": "01",  # 만기일시상환
            "repay_org_code": ORG_BANK["code"], "repay_account_num": f"110{uid:03d}0001",
        })
        details.append({
            "account_num": account_num, "seqno": "1", "currency_code": "KRW",
            "balance_amt": alloc["bank_loan"], "loan_principal": alloc["bank_loan"], "next_repay_date": _d(now + timedelta(days=20)),
        })
        # 이자 납부 내역
        monthly_interest = round(alloc["bank_loan"] * 0.038 / 12, -2)
        for ms, _ in _month_starts(now):
            if ms.replace(day=25) <= now:
                trans.append({
                    "account_num": account_num, "trans_dtime": _dt(ms.replace(day=25, hour=10)),
                    "trans_no": f"L{_d(ms)}{uid}", "trans_type": "02",  # 이자납입
                    "trans_amt": monthly_interest, "balance_amt": alloc["bank_loan"],
                    "principal_amt": 0, "int_amt": monthly_interest, "currency_code": "KRW",
                })

    return _resp({"loan_cnt": len(loans), "loan_list": loans,
                  "basic_list": basics, "detail_list": details, "trans_list": trans})


# ---------------------------------------------------------------------------
# 카드 (카드-001 ~ 012)
# ---------------------------------------------------------------------------
def gen_card_list(spec: dict, alloc: dict, now: datetime) -> dict:
    uid = spec["id"]
    names = ["AFPA 청년카드", "AFPA 트래블카드", "AFPA 체크카드"]
    cards = []
    for i in range(alloc["cards"]):
        cards.append({
            "card_id": f"CARD{uid:03d}{i + 1:02d}",
            "card_num": f"9410-****-****-{uid:02d}{i + 1:02d}",
            "is_consent": True, "card_name": names[i],
            "card_member": "1",  # 본인
            "card_type": "03" if i == 2 else "01",  # 01 신용, 03 체크
            "card_brand": "04",  # 국내전용
            "annual_fee": 0 if i == 2 else 15_000,
            "issue_date": "20230201" if uid != 3 else "20240901",
        })
    return _resp({"card_cnt": len(cards), "card_list": cards})


def gen_card_approvals(spec: dict, alloc: dict, now: datetime) -> dict:
    """국내 승인내역 — 변동지출을 가맹점별로 분산. 이번 달은 factor 반영"""
    uid = spec["id"]
    approvals = []
    seq = 0

    for ms, max_day in _month_starts(now):
        is_current = ms.month == now.month and ms.year == now.year
        base = spec["monthly_spending"] * random.uniform(0.9, 1.1)
        if is_current:
            base = spec["monthly_spending"] * spec["current_month_factor"] * now.day / 30

        for category, (ratio, merchants, biz_code) in CATEGORY_MERCHANTS.items():
            cat_total = base * ratio
            n_tx = random.randint(3, 8)
            for _ in range(n_tx):
                seq += 1
                amt = round(cat_total / n_tx * random.uniform(0.7, 1.3), -2)
                day = random.randint(1, max_day)
                ts = ms.replace(day=day, hour=random.randint(9, 21), minute=random.randint(0, 59))
                card_no = random.randint(1, alloc["cards"])
                approvals.append({
                    "card_id": f"CARD{uid:03d}{card_no:02d}",
                    "approved_num": f"A{seq:010d}", "approved_dtime": _dt(ts),
                    "status": "01",  # 승인
                    "pay_type": "01",  # 일시불
                    "merchant_name": random.choice(merchants), "merchant_regno": f"{biz_code}00{uid:03d}",
                    "approved_amt": amt, "modified_amt": None,
                    "total_install_cnt": None, "krw_amt": None, "foreign_yn": False,
                    "_category": category,  # 어댑터용 힌트 (규격 외 내부 필드)
                })

        # 구독서비스 (고정, 매월 1일)
        sub_amt = round(spec["profile"]["monthly_fixed_expense"] * 0.05 / len(SUBSCRIPTION_MERCHANTS), -2)
        for m in SUBSCRIPTION_MERCHANTS:
            seq += 1
            approvals.append({
                "card_id": f"CARD{uid:03d}01",
                "approved_num": f"A{seq:010d}", "approved_dtime": _dt(ms.replace(day=1, hour=7)),
                "status": "01", "pay_type": "01",
                "merchant_name": m, "merchant_regno": "5968001",
                "approved_amt": sub_amt, "modified_amt": None,
                "total_install_cnt": None, "krw_amt": None, "foreign_yn": False,
                "_category": "구독서비스", "_is_fixed": True,
            })

    return _resp({"approved_cnt": len(approvals), "approved_list": approvals})


def gen_card_bills(spec: dict, alloc: dict, now: datetime) -> dict:
    bills = []
    for ms, _ in _month_starts(now):
        if ms.replace(day=14) <= now:
            bills.append({
                "charge_month": ms.strftime("%Y%m"), "charge_day": 14,
                "charge_amt": round(spec["monthly_spending"], -2),
                "card_type": "01", "paid_out_date": _d(ms.replace(day=14)),
            })
    return _resp({"bill_cnt": len(bills), "bill_list": bills})


def gen_card_points(spec: dict, alloc: dict, now: datetime) -> dict:
    return _resp({"point_cnt": 1, "point_list": [{
        "point_name": "AFPA포인트", "remain_point_amt": spec["id"] * 3_500,
        "expiring_point_amt": 500, "expiring_date": _d(now + timedelta(days=60)),
    }]})


def gen_card_loans(spec: dict, alloc: dict, now: datetime) -> dict:
    """카드-009~012: 리볼빙/단기(현금서비스)/장기(카드론)"""
    revolving, short_term, long_term = [], [], []
    if alloc["card_revolving"] > 0:
        revolving.append({
            "type": "01", "min_pay_rate": 10.0, "monthly_pay_amt": round(alloc["card_revolving"] * 0.1, -2),
            "remain_amt": alloc["card_revolving"], "agreed_rate": 17.5,
        })
    if alloc["card_short_loan"] > 0:
        short_term.append({
            "loan_dtime": _dt(now - timedelta(days=45)), "loan_amt": alloc["card_short_loan"],
            "remain_amt": alloc["card_short_loan"], "int_rate": 18.9,
            "exp_date": _d(now + timedelta(days=45)), "pay_method": "01",
        })
    return _resp({
        "revolving_cnt": len(revolving), "revolving_list": revolving,
        "short_term_cnt": len(short_term), "short_term_list": short_term,
        "long_term_cnt": len(long_term), "long_term_list": long_term,
    })


# ---------------------------------------------------------------------------
# 금투 (금투-001 ~ 004)
# ---------------------------------------------------------------------------
def gen_invest_accounts(spec: dict, alloc: dict, now: datetime) -> dict:
    uid = spec["id"]
    accounts, basics, trans, products = [], [], [], []

    if alloc["invest"] > 0:
        account_num = f"310{uid:03d}0001"
        accounts.append({
            "account_num": account_num, "is_consent": True,
            "account_name": "AFPA 종합매매계좌", "account_type": "101", "account_status": "01",
        })
        cash = round(alloc["invest"] * 0.1, -2)
        basics.append({
            "account_num": account_num, "currency_code": "KRW",
            "withholdings_amt": cash,           # 예수금
            "credit_loan_amt": 0, "mortgage_amt": 0,
            "issue_date": "20230501",
        })
        # 보유상품: ETF + 펀드로 배분
        etf_amt = round((alloc["invest"] - cash) * 0.6, -2)
        fund_amt = alloc["invest"] - cash - etf_amt
        products = [
            {"account_num": account_num, "prod_type": "401", "prod_name": "KODEX 200 ETF",
             "prod_code": "069500", "purchase_amt": round(etf_amt * 0.92, -2),
             "holding_num": max(int(etf_amt / 38000), 1), "eval_amt": etf_amt,
             "currency_code": "KRW"},
            {"account_num": account_num, "prod_type": "301", "prod_name": "AFPA 글로벌성장펀드",
             "prod_code": "K55301", "purchase_amt": round(fund_amt * 0.95, -2),
             "holding_num": None, "eval_amt": fund_amt, "currency_code": "KRW"},
        ]
        # 거래내역: 월 적립 매수
        monthly_buy = 200_000 if uid == 1 else (500_000 if uid == 2 else 50_000)
        for ms, _ in _month_starts(now):
            if ms.replace(day=5) <= now:
                trans.append({
                    "account_num": account_num, "trans_dtime": _dt(ms.replace(day=5, hour=10)),
                    "trans_no": f"I{_d(ms)}{uid}", "trans_type": "01",  # 매수
                    "trans_type_detail": "ETF매수", "prod_name": "KODEX 200 ETF",
                    "trans_amt": monthly_buy, "settle_amt": monthly_buy,
                    "balance_amt": None, "currency_code": "KRW",
                })

    return _resp({"account_cnt": len(accounts), "account_list": accounts,
                  "basic_list": basics, "trans_list": trans, "product_list": products})


# ---------------------------------------------------------------------------
# 보험 (보험-001 ~ 005)
# ---------------------------------------------------------------------------
def gen_insurances(spec: dict, alloc: dict, now: datetime) -> dict:
    uid = spec["id"]
    fixed = spec["profile"]["monthly_fixed_expense"]
    total_prem = round(fixed * 0.20, -2)  # 고정지출 중 보험 비중

    insu_list, basics, cars, payments = [], [], [], []

    def add_insu(no, name, itype, prem, is_car=False):
        insu_num = f"INS{uid:03d}{no:02d}"
        insu_list.append({
            "insu_num": insu_num, "is_consent": True, "prod_name": name,
            "insu_type": itype, "insu_status": "02",  # 정상유지
        })
        basics.append({
            "insu_num": insu_num, "is_renewable": True,
            "issue_date": "20230301", "exp_date": _d(now + timedelta(days=365 * 10)),
            "face_amt": 100_000_000 if itype == "05" else 30_000_000,
            "currency_code": "KRW", "is_variable": False, "is_universal": False,
        })
        payments.append({
            "insu_num": insu_num, "pay_due": "01",  # 매월
            "pay_cycle": "1M", "pay_cnt": None,
            "pay_org_code": ORG_BANK["code"], "pay_date": "25",
            "pay_end_date": _d(now + timedelta(days=365 * 5)),
            "pay_amt": prem, "currency_code": "KRW",
        })
        if is_car:
            cars.append({
                "insu_num": insu_num, "car_number": f"12가{uid}456",
                "car_insu_type": "01", "car_name": "쏘렌토 하이브리드",
                "start_date": _d(now - timedelta(days=180)), "end_date": _d(now + timedelta(days=185)),
                "contract_age": "만26세이상", "contract_driver": "부부한정",
                "is_own_dmg_coverage": True, "self_pay_rate": "20%",
            })

    if alloc["has_car_insu"]:
        car_prem = round(total_prem * 0.35, -2)
        add_insu(1, "AFPA 실손의료보험", "01", round(total_prem * 0.3, -2))
        add_insu(2, "AFPA 자동차보험", "04", car_prem, is_car=True)
        add_insu(3, "AFPA 종신보험", "05", total_prem - car_prem - round(total_prem * 0.3, -2))
    else:
        add_insu(1, "AFPA 실손의료보험", "01", total_prem)

    return _resp({"insu_cnt": len(insu_list), "insu_list": insu_list,
                  "basic_list": basics, "car_list": cars, "payment_list": payments})


# ---------------------------------------------------------------------------
# 전금 (전금-001 ~ 005)
# ---------------------------------------------------------------------------
def gen_efin(spec: dict, alloc: dict, now: datetime) -> dict:
    uid = spec["id"]
    trans = []
    # 월 2~4회 충전/결제
    for ms, max_day in _month_starts(now):
        for _ in range(random.randint(2, 4)):
            day = random.randint(1, max_day)
            ts = ms.replace(day=day, hour=random.randint(10, 20))
            amt = random.choice([10_000, 20_000, 30_000, 50_000])
            trans.append({
                "trans_dtime": _dt(ts), "trans_no": f"E{_dt(ts)}{uid}",
                "trans_type": "01" if random.random() < 0.4 else "02",  # 01 충전, 02 결제
                "trans_amt": amt, "balance_amt": alloc["efin_balance"],
                "merchant_name": random.choice(["편의점", "카페", "온라인쇼핑"]) if random.random() > 0.4 else None,
            })
    return _resp({
        "account_cnt": 1,
        "account_list": [{
            "account_id": f"PAY{uid:03d}", "is_consent": True,
            "account_type": "01",  # 선불
            "account_status": "01",
        }],
        "balance_list": [{"account_id": f"PAY{uid:03d}", "balance_amt": alloc["efin_balance"],
                          "charge_amt": 50_000, "reserved_amt": 0}],
        "trans_cnt": len(trans), "trans_list": trans,
    })


# ---------------------------------------------------------------------------
# 통신 (통신-001 ~ 004)
# ---------------------------------------------------------------------------
def gen_telecom(spec: dict, alloc: dict, now: datetime) -> dict:
    uid = spec["id"]
    fixed = spec["profile"]["monthly_fixed_expense"]
    monthly_fee = round(fixed * 0.10, -2)
    lines = 2 if uid == 2 else 1

    bills, paids = [], []
    for ms, _ in _month_starts(now):
        if ms.replace(day=25) <= now:
            bills.append({"charge_month": ms.strftime("%Y%m"), "charge_amt": monthly_fee})
            paids.append({
                "paid_dtime": _dt(ms.replace(day=25, hour=12)), "paid_amt": monthly_fee,
                "pay_method": "02",  # 계좌이체
                "pay_org_code": ORG_BANK["code"],
            })

    return _resp({
        "contract_cnt": lines,
        "contract_list": [
            {"contract_id": f"TEL{uid:03d}{i + 1:02d}", "is_consent": True,
             "contract_type": "01", "contract_status": "01",
             "plan_name": "5G 스탠다드" if i == 0 else "5G 라이트",
             "device_installment": 250_000 if uid == 3 and i == 0 else 0}
            for i in range(lines)
        ],
        "bill_list": bills, "paid_list": paids,
    })


# ---------------------------------------------------------------------------
# IRP (IRP-001 ~ 004)
# ---------------------------------------------------------------------------
def gen_irp(spec: dict, alloc: dict, now: datetime) -> dict:
    accounts, basics, details, trans = [], [], [], []
    uid = spec["id"]
    if alloc["irp"] > 0:
        account_num = f"410{uid:03d}0001"
        accounts.append({
            "account_num": account_num, "is_consent": True,
            "account_status": "01", "prod_name": "AFPA IRP 계좌",
        })
        basics.append({
            "account_num": account_num, "accum_amt": alloc["irp"],
            "issue_date": "20220301", "open_date": "20220301",
        })
        details.append({
            "account_num": account_num, "irp_prod_name": "AFPA IRP 정기예금형",
            "eval_amt": alloc["irp"], "invest_principal": round(alloc["irp"] * 0.9, -2),
            "fee_amt": 12_000,
        })
        for ms, _ in _month_starts(now):
            if ms.replace(day=10) <= now:
                trans.append({
                    "account_num": account_num, "trans_dtime": _dt(ms.replace(day=10, hour=9)),
                    "trans_type": "01",  # 입금(납입)
                    "trans_amt": 300_000, "currency_code": "KRW",
                })
    return _resp({"account_cnt": len(accounts), "account_list": accounts,
                  "basic_list": basics, "detail_list": details, "trans_list": trans})


# ---------------------------------------------------------------------------
# 할부금융 (할부금융-001 ~ 006)
# ---------------------------------------------------------------------------
def gen_capital(spec: dict, alloc: dict, now: datetime) -> dict:
    loans, basics, details, trans = [], [], [], []
    uid = spec["id"]
    if alloc["capital_loan"] > 0:
        account_num = f"510{uid:03d}0001"
        loans.append({
            "account_num": account_num, "is_consent": True, "seqno": "1",
            "prod_name": "AFPA캐피탈 스마트폰 할부", "account_type": "3710",  # 할부금융
            "account_status": "01",
        })
        basics.append({
            "account_num": account_num, "seqno": "1",
            "issue_date": _d(now - timedelta(days=120)), "exp_date": _d(now + timedelta(days=600)),
            "last_offered_rate": 9.9, "repay_date": "15", "repay_method": "02",  # 원리금균등
            "repay_org_code": ORG_BANK["code"], "repay_account_num": f"110{uid:03d}0001",
        })
        details.append({
            "account_num": account_num, "seqno": "1", "currency_code": "KRW",
            "balance_amt": alloc["capital_loan"], "loan_principal": alloc["capital_loan"] + 500_000,
            "next_repay_date": _d(now + timedelta(days=10)),
        })
        monthly_pay = 180_000
        for ms, _ in _month_starts(now):
            if ms.replace(day=15) <= now:
                trans.append({
                    "account_num": account_num, "trans_dtime": _dt(ms.replace(day=15, hour=10)),
                    "trans_type": "01",  # 원리금납입
                    "trans_amt": monthly_pay,
                    "principal_amt": round(monthly_pay * 0.85, -2),
                    "int_amt": round(monthly_pay * 0.15, -2),
                    "balance_amt": alloc["capital_loan"],
                })
    return _resp({"loan_cnt": len(loans), "loan_list": loans,
                  "basic_list": basics, "detail_list": details, "trans_list": trans})


# ---------------------------------------------------------------------------
# 보증보험 (보증보험-001 ~ 003)
# ---------------------------------------------------------------------------
def gen_ginsu(spec: dict, alloc: dict, now: datetime) -> dict:
    insu_list, basics, payments = [], [], []
    uid = spec["id"]
    if alloc["has_ginsu"]:
        insu_num = f"GIN{uid:03d}01"
        insu_list.append({
            "insu_num": insu_num, "is_consent": True,
            "prod_name": "전세금보장신용보험", "insu_status": "02",
        })
        basics.append({
            "insu_num": insu_num, "issue_date": "20240215",
            "exp_date": _d(now + timedelta(days=500)),
            "face_amt": 50_000_000,  # 전세보증금 목표와 연결
            "currency_code": "KRW",
        })
        payments.append({
            "insu_num": insu_num, "pay_due": "03",  # 일시납
            "pay_amt": 180_000, "pay_date": "20240215", "pay_cnt": 1,
        })
    return _resp({"insu_cnt": len(insu_list), "insu_list": insu_list,
                  "basic_list": basics, "payment_list": payments})


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
GENERATORS = {
    "bank_accounts.json": gen_bank_accounts,
    "bank_transactions.json": gen_bank_transactions,
    "bank_loans.json": gen_bank_loans,
    "card_list.json": gen_card_list,
    "card_approvals.json": gen_card_approvals,
    "card_bills.json": gen_card_bills,
    "card_points.json": gen_card_points,
    "card_loans.json": gen_card_loans,
    "invest_accounts.json": gen_invest_accounts,
    "insurance_list.json": gen_insurances,
    "efin_accounts.json": gen_efin,
    "telecom_contracts.json": gen_telecom,
    "irp_accounts.json": gen_irp,
    "capital_loans.json": gen_capital,
    "ginsu_insurances.json": gen_ginsu,
}


def _validate(spec: dict, alloc: dict) -> list:
    """정합성 검증 — persona 총액과 배분 합계 비교"""
    p = spec["profile"]
    errors = []
    dep = alloc["checking"] + alloc["deposit"] + alloc["efin_balance"]
    if abs(dep - p["deposit"]) > 1:
        errors.append(f"deposit 불일치: {dep} != {p['deposit']}")
    if abs(alloc["savings"] - p["savings"]) > 1:
        errors.append(f"savings 불일치: {alloc['savings']} != {p['savings']}")
    if abs(alloc["invest"] - p["investment"]) > 1:
        errors.append(f"investment 불일치: {alloc['invest']} != {p['investment']}")
    if abs(alloc["irp"] - p["other_assets"]) > 1:
        errors.append(f"other_assets(IRP) 불일치: {alloc['irp']} != {p['other_assets']}")
    debt = alloc["bank_loan"] + alloc["card_revolving"] + alloc["card_short_loan"] + alloc["capital_loan"]
    if abs(debt - p["total_debt"]) > 1:
        errors.append(f"total_debt 불일치: {debt} != {p['total_debt']}")
    return errors


def main() -> None:
    with open(PERSONA_FILE, encoding="utf-8") as f:
        personas = json.load(f)

    now = datetime.utcnow()
    print(f"페르소나 {len(personas)}명 로드 ← {PERSONA_FILE.name}")

    for spec in personas:
        alloc = _allocate(spec)

        errors = _validate(spec, alloc)
        if errors:
            raise ValueError(f"[{spec['name']}] 정합성 오류: {errors}")

        user_dir = MYDATA_DIR / f"user_{spec['id']:03d}"
        user_dir.mkdir(parents=True, exist_ok=True)

        # 사용자 메타 (규격 외 — 어댑터가 참조)
        with open(user_dir / "_user.json", "w", encoding="utf-8") as f:
            json.dump({
                "user_id": spec["id"], "name": spec["name"], "job": spec.get("job"),
                "persona_type": spec.get("persona_type"), "description": spec.get("description"),
                "monthly_income": spec["profile"]["monthly_income"],
                "monthly_fixed_expense": spec["profile"]["monthly_fixed_expense"],
                "monthly_variable_expense": spec["profile"]["monthly_variable_expense"],
                "goals": spec["goals"],
            }, f, ensure_ascii=False, indent=2)

        for filename, gen_fn in GENERATORS.items():
            data = gen_fn(spec, alloc, now)
            with open(user_dir / filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"[{spec['name']}] {user_dir.name}/ → {len(GENERATORS) + 1}개 파일 생성 (정합성 OK)")

    print(f"\n✅ 마이데이터 테스트 데이터셋 생성 완료 → {MYDATA_DIR}")


if __name__ == "__main__":
    main()
