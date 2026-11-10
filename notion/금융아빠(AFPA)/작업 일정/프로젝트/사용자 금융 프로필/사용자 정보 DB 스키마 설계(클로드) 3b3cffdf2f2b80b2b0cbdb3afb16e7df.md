# 사용자 정보 DB 스키마 설계(클로드)

> ⚠️ 이 문서는 「사용자 금융 프로필_1차 MVP 버전」 폴더 문서의 **사본**이다. 수정은 MVP 버전 문서를 기준으로 한다.


> AFPA(AI Financial Planning Agent) — 사용자 프로필·온보딩·재무진단 저장 스키마 관련 문서: 「금융 프로필 산출 로직」(지표 정의), 「데이터 분류 로직」
> 

---

## 1. 설계 개요

사용자 데이터를 성격에 따라 세 테이블로 분리한다.

| 테이블 | 성격 | 변경 빈도 |
| --- | --- | --- |
| `users` | 회원 계정 정보 | 거의 불변 |
| `user_profiles` | 온보딩 입력값 (인적·환경 정보) | 사용자가 수정 시 |
| `financial_snapshots` | 재무진단 결과 (지표) | 동기화 때마다 누적 |
| `mydata_consents` | 마이데이터 항목별 동의 상태 | 동의·철회 시 |
| `merchant_category_overrides` | 사용자 분류 수정 이력 (학습용) | 사용자가 수정 시 |
| `manual_assets` | 마이데이터에 없는 수동 자산 (금 현물 등) | 사용자가 수정 시 |

**핵심 원칙:** 재무진단 지표(건강도·저축률·DSR 등)는 마이데이터 동기화 때마다 값이 바뀌는 시계열이므로, 프로필에 단일 컬럼으로 두지 않고 **스냅샷 이력 테이블에 누적**한다. 이를 통해 추세 분석("지난달 대비 건강도 변화")과 소비·재무 모니터링이 가능해진다.

---

## 2. 스키마 트리

```
📂 [사용자 정보 DB 스키마]
│
├── 👤 [users] — 회원 기본 계정 정보
│   ├── 🔑 user_id (PK) ............... 사용자 식별자 [UUID]
│   ├── 📧 email ..................... 이메일 계정 [Unique, 암호화]
│   ├── 🔒 password_hash ............. 비밀번호 해시 (소셜 로그인만 사용 시 NULL)
│   ├── 📛 name ...................... 사용자 이름 [암호화]
│   ├── 📱 phone_number .............. 본인인증·알림용 휴대폰 번호 [암호화]
│   ├── 🔑 oauth_provider ............ 소셜 로그인 구분 (LOCAL, KAKAO, NAVER, GOOGLE)
│   ├── 🔑 oauth_id .................. 소셜 로그인 고유 식별자 (LOCAL이면 NULL)
│   ├── 🔄 mydata_connected .......... 마이데이터 연동 여부 (Boolean, 기본 False)
│   ├── 🕒 mydata_last_synced_at ..... 마이데이터 최근 동기화 일시 (Nullable)
│   ├── 🕒 created_at ................ 가입일
│   └── 🕒 updated_at ................ 계정 정보 수정일
│
├── 📋 [user_profiles] — 온보딩 입력값 (users와 1:1)
│   ├── 🔑 profile_id (PK) ........... 프로필 식별자 [UUID]
│   ├── 🔗 user_id (FK) .............. 사용자 식별자 [Unique → users.user_id]
│   │
│   ├─ 📝 [기본 인적·환경 정보]
│   │   ├── 🎂 birth_date ............ 생년월일 (나이·청년정책 판별용) [암호화]
│   │   ├── 🚻 gender ................ 성별 (MALE, FEMALE, OTHER, 미입력 시 NULL)
│   │   ├── 💼 employment_status ..... 고용 형태 (FULL_TIME, FREELANCER,
│   │   │                              SELF_EMPLOYED, UNEMPLOYED)
│   │   ├── 🏠 housing_type .......... 거주 형태 (OWNED, JEONSE, MONTHLY_RENT)
│   │   ├── 💵 housing_cost_monthly .. 월세/임대료 (MONTHLY_RENT일 때만, 그 외 NULL)
│   │   ├── 📍 location_region ....... 거주 지역 시/도 (예: 서울, 경기)
│   │   ├── 📍 location_district ..... 거주 지역 구/군 (예: 강남구, 분당구)
│   │   └── 🎯 risk_tolerance ........ 투자 성향 (CONSERVATIVE, BALANCED, AGGRESSIVE)
│   │
│   └─ 🕒 [메타]
│       ├── 🕒 created_at ........... 프로필 최초 생성일
│       └── 🕒 updated_at ........... 프로필 최신 수정일
│
└── 📊 [financial_snapshots] — 재무진단 결과 이력 (users와 1:N)
    ├── 🔑 snapshot_id (PK) .......... 스냅샷 식별자 [UUID]
    ├── 🔗 user_id (FK) .............. 사용자 식별자 [→ users.user_id]
    ├── 🕒 calculated_at ............. 진단 산출 일시 (추세 정렬 기준)
    │
    ├─ 💵 [소득]
    │   └── monthly_income_net ....... 세후 월 평균 소득 (마이데이터/직접입력 산출)
    │
    ├─ 📊 [4대 재무 진단 지표]
    │   ├── 📈 savings_ratio ......... 저축성향지수 (%) = (월 저축액 / 월 수입) × 100
    │   ├── 📉 dsr_ratio ............. 부채상환부담률 DSR (%)
    │   │                              = (월 대출 원리금 / 월 수입) × 100
    │   ├── 🛡️ emergency_fund_ratio .. 비상금 충당률 (%)
    │   │                              = (현금성 자산 / 3개월치 필수지출) × 100
    │   └── 🛒 consumption_ratio ..... 소비성향지수 (%) = (월 총지출 / 월 수입) × 100
    │
    └─ 🏆 [종합]
        ├── health_score ............ 종합 금융 건강도 (0~100, 4대 지표 가중합)
        └── potential_score ......... 금융 잠재력 (0~100, 목표 진척·저축 여력·소득 성장성·시간 여유)

    (보조 지표: net_cash_flow 월 여유 자금, net_worth 순자산, debt_ratio 부채 비율)
```

---

## 3. 테이블 상세

### 3.1 users — 회원 계정

| 컬럼 | 타입 | 제약 | 비고 |
| --- | --- | --- | --- |
| user_id | UUID | PK |  |
| email | VARCHAR | Unique, NOT NULL | 암호화 저장 |
| password_hash | VARCHAR | Nullable | 소셜 전용 계정은 NULL |
| name | VARCHAR | NOT NULL | 암호화 저장 |
| phone_number | VARCHAR |  | 암호화 저장 |
| oauth_provider | ENUM | NOT NULL | LOCAL/KAKAO/NAVER/GOOGLE |
| oauth_id | VARCHAR | Nullable | LOCAL이면 NULL |
| mydata_connected | BOOLEAN | 기본 FALSE |  |
| mydata_last_synced_at | TIMESTAMP | Nullable |  |
| created_at | TIMESTAMP | NOT NULL |  |
| updated_at | TIMESTAMP | NOT NULL |  |

### 3.2 user_profiles — 온보딩 입력 (1:1)

| 컬럼 | 타입 | 제약 | 비고 |
| --- | --- | --- | --- |
| profile_id | UUID | PK |  |
| user_id | UUID | FK, Unique | users.user_id |
| birth_date | DATE |  | 암호화 저장 |
| gender | ENUM | Nullable | MALE/FEMALE/OTHER |
| employment_status | ENUM |  | FULL_TIME/FREELANCER/SELF_EMPLOYED/UNEMPLOYED |
| housing_type | ENUM |  | OWNED/JEONSE/MONTHLY_RENT |
| housing_cost_monthly | INTEGER | Nullable | MONTHLY_RENT일 때만 |
| location_region | VARCHAR |  | 시/도 |
| location_district | VARCHAR |  | 구/군 |
| risk_tolerance | ENUM |  | CONSERVATIVE/BALANCED/AGGRESSIVE |
| created_at | TIMESTAMP | NOT NULL |  |
| updated_at | TIMESTAMP | NOT NULL |  |

### 3.3 financial_snapshots — 진단 결과 이력 (1:N)

| 컬럼 | 타입 | 제약 | 비고 |
| --- | --- | --- | --- |
| snapshot_id | UUID | PK |  |
| user_id | UUID | FK | users.user_id |
| calculated_at | TIMESTAMP | NOT NULL | 추세 정렬 기준, 인덱스 권장 |
| monthly_income_net | INTEGER |  | 세후 월 평균 소득 |
| savings_ratio | DECIMAL(5,2) |  | 저축성향지수 (%) |
| dsr_ratio | DECIMAL(5,2) |  | 부채상환부담률 (%) |
| emergency_fund_ratio | DECIMAL(5,2) |  | 비상금 충당률 (%) |
| consumption_ratio | DECIMAL(5,2) |  | 소비성향지수 (%) |
| health_score | INTEGER |  | 0~100, 현황 축 |
| potential_score | INTEGER |  | 0~100, 전망 축 (산출 로직 2.6) |
| net_cash_flow | INTEGER |  | 월 여유 자금 (사용자 노출 대표 지표, D-02) |
| net_worth | BIGINT |  | 순자산 |
| debt_ratio | DECIMAL(5,2) |  | 부채 비율 (%) |

> `(user_id, calculated_at)` 복합 인덱스를 두면 "사용자별 최신 스냅샷 조회"와 "기간별 추세 조회"가 모두 빨라진다. 최신 프로필은 해당 user_id에서 `calculated_at` 최대 행을 읽는다.
> 

### 3.4 mydata_consents — 항목별 동의 상태

| 컬럼 | 타입 | 제약 | 비고 |
| --- | --- | --- | --- |
| consent_id | UUID | PK |  |
| user_id | UUID | FK | users.user_id |
| is_consent_merchant_name_regno | BOOLEAN | NOT NULL | 가맹점명·사업자번호 |
| is_consent_trans_memo | BOOLEAN | NOT NULL | 적요·거래메모 |
| is_consent_trans_category | BOOLEAN | NOT NULL | 상품(구매)분류 |
| consented_at / revoked_at | TIMESTAMP | Nullable | 이력 보존, 철회 시 해당 필드 기반 분류 중단 |

### 3.5 merchant_category_overrides — 사용자 분류 수정 이력

| 컬럼 | 타입 | 제약 | 비고 |
| --- | --- | --- | --- |
| override_id | UUID | PK |  |
| user_id | UUID | FK |  |
| merchant_name_norm | VARCHAR | NOT NULL | 정규화된 가맹점명 |
| category | VARCHAR | NOT NULL | 사용자가 지정한 분류 |
| created_at | TIMESTAMP | NOT NULL | 이후 동일 상호는 분류 1단계에서 즉시 적용 |

### 3.6 manual_assets — 수동 자산

| 컬럼 | 타입 | 제약 | 비고 |
| --- | --- | --- | --- |
| asset_id | UUID | PK |  |
| user_id | UUID | FK |  |
| asset_type | ENUM | NOT NULL | CASH / GOLD / OTHER |
| name | VARCHAR |  | 항목명 |
| amount | BIGINT | NOT NULL | 평가액(원) |
| updated_at | TIMESTAMP | NOT NULL | 갱신 일자, 오래되면 갱신 안내 |

---

## 4. 유의사항

- **개인정보 암호화:** `email`·`name`·`phone_number`·`birth_date`는 개인정보로 암호화 저장 대상이다. 마이데이터 서비스 특성상 관련 법·가이드라인의 저장·전송 보안 요건을 따른다.
- **마이데이터 파기 정책:** 「개인정보 보호 및 데이터 파기 정책」에 따른다. 연동 해지 시 수집 원본·분류 결과는 삭제하고, 스냅샷 처리 방식은 해당 문서의 미결 사항으로 관리한다.
- **지표 명칭:** 부채 지표는 모든 대출 원리금을 분자로 하므로 DTI가 아닌 **DSR**로 명명한다(「금융 프로필 산출 로직」과 일치).
- **4대 지표 + 종합점수:** savings/dsr/emergency/consumption 4개가 표준 진단 지표이고, `health_score`는 이 4개를 가중합한 상위 종합점수로 성격이 구분된다.
- **소득 예외처리:** 정기수입이 불명확한 사용자는 `monthly_income_net`을 최근 3개월 입금 평균으로 대체하며, 산출 불가 시 해당 스냅샷의 비율 지표는 NULL로 둔다(강제 0 금지).
- **투자성향 위치:** `risk_tolerance`는 1차에서 온보딩 자가입력값이며, 설문 기반 산출(투자 전략 단계) 도입 시 `financial_snapshots` 계열로 이동할 수 있다. 미입력 시 중립형으로 가정한다.