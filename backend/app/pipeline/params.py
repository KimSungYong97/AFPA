"""설계 파라미터 (설계 파라미터 결정표 ID 기준)

「설계 파라미터 결정표」의 값을 코드 상수로 옮긴 것. 값을 바꿀 때는 문서와 함께 수정한다.
"H-" 접두 값은 결정표에 점수 곡선이 명시되지 않아 1차 구현에서 정한 가정값이다.
"""

# ---- 주기성·임계치 (결정표 2절) ------------------------------------------------
RECUR_DAY_TOLERANCE = 3          # P-01/P-02: 기준일 ±3일 (주말·연휴로 인한 이연 흡수)
AMOUNT_TOL_FIXED = 0.10          # P-03: 직전 대비 ±10%
AMOUNT_TOL_UTILITY = 0.30        # P-03: 공과금·통신 ±30%
MIN_OCCURRENCES = 3              # P-04: 최소 3회 이상 반복 (서로 다른 달)
RECUR_CONFORM_RATIO = 0.8        # 구현 가정: 반복 후보 중 80% 이상이 규칙에 맞아야 함
WINDOW_MONTHS_MAX = 6            # P-04: 관측 3~6개월
WINDOW_MONTHS_MIN = 3
OUTLIER_GROWTH = 0.20            # P-05: 직전 3개월 평균 대비 +20%
OUTLIER_MIN_INCOME_SHARE = 0.01  # P-05: 월 소득의 1% 이상
EMERGENCY_MONTHS_DEFAULT = 3     # P-06
EMERGENCY_MONTHS_IRREGULAR = 6   # P-06: 프리랜서·자영업

# ---- 가중치 (결정표 3절) ------------------------------------------------------
HEALTH_WEIGHTS = {"saving": 30, "debt": 30, "emergency": 20, "spending": 20}
POTENTIAL_WEIGHTS = {"velocity": 35, "surplus": 30, "income_growth": 20, "horizon": 15}

# ---- 점수 곡선 (H-: 1차 구현 가정값, 결정표에 미명시) --------------------------
SAVING_TARGET_RATIO = 0.30       # 저축/투자 성향: 월 소득의 30% 이상이면 만점 (FPSB)
DSR_FULL_BELOW = 30.0            # 부채 관리: DSR 30% 이하 만점
DSR_ZERO_AT = 60.0               # 부채 관리: DSR 60% 이상 0점 (30~60% 선형 감소)
SPEND_FULL_BELOW = 0.50          # 소비 통제: 변동지출/수입 50% 이하 만점
SPEND_HALF_AT = 0.70             # 70%에서 50% 득점
SPEND_ZERO_AT = 1.00             # 100% 이상 0점
SURPLUS_TARGET_RATIO = 0.30      # 저축 여력: 여유 자금/수입 30% 이상 만점
HORIZON_FULL_YEARS = 10.0        # 시간 여유: 평균 10년 이상 만점
NO_DATE_GOAL_YEARS = 10.0        # 목표일 없는 목표(예: 은퇴)의 시간 여유 가정

# ---- 등급 -----------------------------------------------------------------
GRADES = [(80, "A"), (60, "B"), (40, "C"), (20, "D"), (0, "E")]

# ---- 프로필 비상금 산정용 필수 변동 카테고리 (산출 로직 2.3) -----------------------
ESSENTIAL_VARIABLE_CATEGORIES = {"식비", "교통", "의료/건강"}

# ===========================================================================
# 2차 통합 플래너 파라미터
# 설계 파라미터 결정표 E-/R- ID 기준. "G-" 접두 값은 결정표에 수치가 없어 2차 구현에서 정한 가정값이다.
# ===========================================================================
# E-01: 자산군별 기본 수익률 가정 — 2차는 목표 적립금을 예금·현금성으로 굴린다고 가정 (연, 세전)
RETURN_ASSUMPTIONS = {"conservative": 0.02, "base": 0.03, "optimistic": 0.04}
DEFAULT_RETURN_CASE = "conservative"        # 설계: 기본 경로는 보수적 값
PATH_HORIZON_MONTHS = 600                   # 50년 안에 못 끝내면 '달성 불가'로 본다
SERIES_MONTHS = 120                         # 경로 그래프용 시계열 길이 상한

# E-02: 경로 이탈 / 재설계 트리거 (결정표 5절과 동일)
DEVIATION_BUDGET_RATIO = 0.10               # 월 여유 자금이 계획 대비 10% 이상 부족(또는 변화)
DEVIATION_DELAY_MONTHS = 2                  # 달성 예상 시기 2개월 이상 지연(또는 변화)
REPLAN_COOLDOWN_DAYS = 30                   # 거절한 사유는 30일간 재제안 금지 (알림 설계 7절)

# E-03: 시나리오 동시 비교 수
MAX_SCENARIOS = 3

# G-: 행동 후보 규칙 (소비 절감)
G_CUT_RATE_NONESSENTIAL = 0.15              # 비필수 카테고리 평균 지출의 15% 절감 제안
G_NONESSENTIAL = {"카페/간식", "쇼핑", "문화/여가", "기타"}
G_MIN_SAVING_INCOME_SHARE = 0.005           # 월 절감액이 월 소득의 0.5% 미만이면 후보에서 제외(노이즈)
G_MIN_SAVING_ABS = 10_000
G_CASH_EXCESS_MIN = 1_000_000               # 과다 현금 이동 제안의 최소 초과액
G_CHECKING_RATE = 0.001                     # 입출금 금리 가정 (연)
G_DEPOSIT_RATE = 0.03                       # 저축성(예금) 금리 가정 (연) — 3차에서 실제 상품 금리로 교체
G_EMERGENCY_FILL_MONTHS = 12                # 비상금 부족분을 이 기간 안에 채우는 속도로 제안
G_TOP_ACTIONS = 5                           # 브리핑·Action Plan에 담는 후보 수

# G-: 소비 변화 판정
G_ONE_OFF_CATEGORIES = {"의료/건강"}          # 일회성 성격 카테고리(확정 전 초기 목록, 일시적 변화로 판정)
G_DECREASE_RATIO = 0.20                     # 급감 판정(-20%)
G_INCOME_CHANGE_RATIO = 0.10                # 수입 변화 판정(±10%)
G_FIXED_INCREASE_RATIO = 0.10               # 고정지출 금액 상승 판정(+10%)

# G-: 이행 추적
G_DONE_RATIO = 0.80                         # 절감 목표의 80% 이상 달성하면 이행(DONE)으로 자동 판정
G_PROPOSAL_EXPIRE_DAYS = 30                 # 제안 후 30일 내 응답이 없으면 만료

# G-: 알림 (알림 설계 4절)
NOTIFY_IMMEDIATE_PER_DAY = 1
NOTIFY_DEDUPE_DAYS = 7

# A-: 변화 감시 에이전트 — 프로필 변화로 볼 최소 폭 (스냅샷 비교)
A_INCOME_CHANGE_RATIO = 0.05                # 월 소득 ±5%
A_BUDGET_CHANGE_RATIO = 0.10                # 월 여유 자금 ±10% (그리고 1만 원 이상)
A_NETWORTH_CHANGE_RATIO = 0.05              # 순자산 ±5%
A_SCORE_CHANGE_POINTS = 5                   # 재무 건강 점수 ±5점
A_RATIO_CHANGE_POINTS = 5                    # DSR·비상금 충족률 ±5%p (스냅샷 값이 % 단위)
A_MAX_TOOL_ROUNDS = 6                       # 에이전트가 도구를 호출할 수 있는 최대 라운드
