# 🤖 AI Financial Planning Agent (AFPA)

> 사용자의 목표를 중심으로 지속적으로 계획을 수립·점검·재설계하는 **목표 기반 금융 의사결정 에이전트**

---

## 1. 프로젝트 개요

### 목적

- 사용자의 금융 목표(집 구매, 결혼, 여행, 차량 구매 등) 달성을 지원하는 **AI Financial Planning Agent**를 구축한다.
- 사용자의 금융 상태, 소비 패턴, 금융상품, 정책 및 규제 정보를 종합적으로 분석하여 목표 달성을 위한 **실행 가능한 금융 전략(Action Plan)** 을 제공한다.

### 비전

단순한 가계부나 금융 추천 서비스가 아닌,

> **"사용자의 목표를 중심으로 지속적으로 계획을 수립·점검·재설계하는 목표 기반 금융 의사결정 에이전트"**

를 지향한다.

---

## 2. 프로젝트 참여자

| 이름 | 역할 |
|------|------|
| 김주영 | 팀장 |
| 김성용 | 개발(꼬봉) |

---

## 3. 프로젝트 목표

- ✅ 목표 달성을 위한 **개인화 금융 전략** 제공
- ✅ 단순 자산 조회가 아닌 **목표 기반 의사결정** 지원
- ✅ 금융 환경 변화에 따라 **지속적으로 전략 업데이트**
- ✅ 사용자의 **소비 습관 및 금융 행동 개선** 유도
- ✅ 금융 목표 달성 가능성을 **정량적으로 분석**

---

## 4. 작업 일정

> 📅 페이지: 작업 일정 (별도 관리)

---

## 5. 서비스 구성

### 5.1 사용자 금융 프로필

**목적** — 사용자의 현재 금융 상태를 분석하고, 모든 Agent가 활용할 기본 금융 프로필을 생성한다.

#### 입력 데이터

| 구분 | 항목 |
|------|------|
| 수입 및 지출 | 월 소득, 월 고정 지출, 월 변동 지출 |
| 자산 | 예금, 적금, 투자 자산, 기타 자산 |
| 부채 | 대출 현황 |
| 금융 상품 | 보험, 카드 |

#### 주요 기능

- **자산 분석**: 자산 현황 분석, 자산 비율 분석, 현금 흐름 분석
- **소비 분석**: 소비 패턴 분석, 소비 카테고리 분석
- **금융 건강도 분석**: 자산 대비 부채, 저축률, 현금 보유율, 금융 건강도 점수 계산

#### 출력

- 자산 요약
- 소비 요약
- 금융 프로필

---

### 5.2 목표 관리

**목적** — 사용자의 금융 목표를 체계적으로 관리한다.

#### 입력 데이터

| 구분 | 예시 |
|------|------|
| 장기 목표 | 내 집 마련, 결혼 자금, 은퇴 준비 |
| Life Event | 여행, 차량 구매, 노트북 구매 |

#### 주요 기능

- 목표 생성 / 수정 / 삭제
- 목표 우선순위 설정
- 목표별 필요 자금 계산
- 목표 달성 가능성 분석

#### 출력

- 목표 리스트
- 목표 달성 예상 시기
- 부족 자금
- 목표 우선순위

---

### 5.3 사용자 목표 관련 금융 정보 수집

**목적** — 사용자의 목표 달성에 필요한 최신 금융 정보를 수집한다.

#### 수집 대상

| 구분 | 항목 |
|------|------|
| 금융상품 | 예금, 적금, 카드, 보험, 대출 상품 |
| 정책 | 청년 정책, 부동산 정책, 정부 지원 정책 |
| 시장 정보 | 기준금리, 예금금리, 대출금리, 금융시장 동향 |

#### 주요 기능

- 실시간 정보 검색
- 목표 기반 정보 필터링
- 변경 사항 추적
- 사용자 관련 정보 선별

#### 출력

- 사용자 맞춤 금융 정보

---

### 5.4 Financial Planning Agent

**목적** — 사용자의 금융 상태와 목표를 분석하여 목표 달성을 위한 실행 가능한 금융 전략(Action Plan)을 생성한다.

#### 입력

- **사용자 정보**: 금융 프로필, 목표, Life Event
- **외부 정보**: 금융상품 정보, 금융 정책 및 규제, 금리 정보

#### 주요 기능

##### ✅ Phase 1. 기본 자산 관리 (MVP)

- **수입 / 지출 분석**: 소비 카테고리 분류, 월별 소비 분석, 고정/변동 지출 분석, 소비 패턴 분석
- **자산 현황 분석**: 자산 분포 분석, 자산 비율 시각화, 현금 흐름 분석
- **지출 개선**: 불필요한 소비 탐지, 절약 가능 항목 추천, 목표 대비 소비 분석
- **자산 리밸런싱**: 현금 비중 제안, 예금 비중 제안, 비상금 규모 제안, 투자 가능 금액 제안

##### ✅ Phase 2. 예·적금 전략

- 사용자 목표 기반 상품 추천
- 금리 비교 / 우대금리 분석
- 만기 시뮬레이션
- 예·적금 리밸런싱

##### ✅ Phase 3. 대출 전략

- **대상**: 신용대출, 주택담보대출, 전세대출
- **기능**: 대출 상품 비교, 상환 전략 수립, DSR/LTV 반영, 정책 반영, 대출 가능성 분석

##### ✅ Phase 4. 투자 전략

- 투자 성향 분석
- 자산 배분 전략
- 리밸런싱
- 투자 비중 제안

> ※ 개별 종목 추천이 아닌 **자산 배분 중심**

#### 출력

- **Action Plan**: 사용자 목표 달성을 위한 실행 가능한 금융 전략
- **추천 근거 제공**: 추천 이유 설명, 사용자 상황 기반 분석, 금융상품 비교, 정책 및 규제 반영 내용

---

### 5.5 사용자 소비 변화 모니터링

**목적** — 목표 달성에 영향을 주는 소비 패턴 변화를 감지한다.

#### 주요 기능

- 소비 패턴 변화 감지
- 고정 지출 변화 감지
- 과도한 지출 감지
- 저축률 변화 감지
- 목표 이탈 감지

#### 출력 예시

> 💬 "이번 달 소비가 평균보다 18% 증가했습니다."
>
> 💬 "현재 소비 패턴이 유지될 경우 목표 달성이 4개월 지연될 것으로 예상됩니다."

---

### 5.6 금융 정보 변화 모니터링

**목적** — 사용자의 금융 전략에 영향을 주는 금융 환경 변화를 감지한다.

#### 모니터링 대상

- 기준금리 변경
- 금융상품 변경
- 카드 혜택 변경
- 대출 규제 변경
- 정부 정책 변경
- 청년 지원 정책 변경

#### 주요 기능

- 변경 사항 감지
- 사용자 영향 분석
- 영향도 계산

#### 출력 예시

> 💬 "현재 가입 가능한 적금 중 더 높은 금리의 상품이 출시되었습니다."
>
> 💬 "대출 규제가 변경되어 기존 계획에 영향이 예상됩니다."

---

### 5.7 계획 재설계 (Re-Planning Agent)

**목적** — 사용자 소비 변화 및 금융 환경 변화에 따라 기존 계획을 재설계한다.

#### 입력

- **내부 데이터**: 소비 변화 모니터링 결과, 목표 달성 현황
- **외부 데이터**: 금리 변동, 정책 변경, 금융상품 변경

#### 주요 기능

- 목표 영향 분석
- 기존 계획 검증
- 전략 재계산
- 우선순위 재조정
- 새로운 Action Plan 생성

#### 출력 예시

> 💬 "현재 소비 증가로 인해 목표 달성 시점이 3개월 지연될 것으로 예상됩니다."
>
> 💬 "월 저축액을 20만원 증액하면 기존 목표 일정을 유지할 수 있습니다."

---

### 5.8 금융 전략 제공 (최종 Agent)

**목적** — 단순 추천이 아닌 **실행 가능한 금융 전략(Action Plan)** 을 제공한다.

#### 주요 기능

- **Action Plan 생성**
  - 저축 금액 조정
  - 소비 절감 제안
  - 카드 변경 제안
  - 대출 상환 순서 제안
  - 예·적금 변경 제안
  - 투자 비중 조정
- **추천 근거 제공**
  - 추천 이유 설명
  - 사용자 상황 기반 설명
  - 금융상품 비교 결과
  - 정책 반영 내용
- **What-if Simulation** *(향후 고도화)*
  - 여행을 가면?
  - 차량을 구매하면?
  - 월 저축액을 늘리면?
  - 보너스를 투자하면?

#### 출력

| 항목 | 내용 |
|------|------|
| Action Plan | 실행 가능한 금융 전략 |
| 추천 이유 | 전략 수립 근거 설명 |
| 예상 결과 | 목표 달성 가능성, 예상 달성 시점 변화, 기대 효과 |

---

## 6. Financial Planning Roadmap

```text
Phase 1 : 기본 자산 관리 (MVP)     ← 현재 진행 중
Phase 2 : 예·적금 전략
Phase 3 : 대출 전략
Phase 4 : 투자 전략
Phase 5 : 금융 모니터링
Phase 6 : Autonomous Financial Agent
```

---

## 7. 구현 현황 (2026-08-04 기준)

### 7.1 서비스별 구현 상세

#### ✅ 5.1 사용자 금융 프로필

| 항목 | 내용 |
|------|------|
| 구현 위치 | `app/services/profile_service.py`, `app/api/profile.py` |
| API | `PUT /api/profile/{user_id}` (등록/수정), `GET /api/profile/{user_id}/summary` (요약) |
| 구현 기능 | 총자산/순자산/월 여유자금 계산, 저축률·부채비율·현금보유율 산출 |
| 건강도 점수 | `_calc_health_score()` — 저축률 40점(30% 이상 만점) + 부채비율 30점(0% 만점) + 비상금 30점(월지출 6개월치 만점) = 0~100점, A~E 등급 |
| 테스트 | `tests/test_profile_service.py` (4개 통과) |

#### ✅ 5.2 목표 관리

| 항목 | 내용 |
|------|------|
| 구현 위치 | `app/services/goal_service.py`, `app/api/goals.py` |
| API | 목표 CRUD (`POST/GET/PUT/DELETE`), `GET /api/goals/item/{goal_id}/feasibility` |
| 달성 가능성 분석 | `analyze_feasibility()` — 부족 자금, 목표일 기준 필요 월 저축액, 현재 여유자금 기준 예상 달성 시기, 달성 가능 여부 판정 |

#### 🔶 5.3 금융 정보 수집 (부분 — API 키 미설정 시 더미)

| 항목 | 내용 |
|------|------|
| 구현 위치 | `app/services/market_service.py`, `app/api/market_data.py` |
| API | `GET /api/market/deposits`, `GET /api/market/savings`, `GET /api/market/base-rate` |
| 구현 상태 | 금감원(FSS) 금융상품 API 호출 코드 완성. `.env`의 `FSS_API_KEY` 미설정 시 더미 상품 반환 |
| 미구현 | 한국은행 ECOS 기준금리(하드코딩 2.50%), 정책 정보 수집 |

#### ✅ 5.4/5.8 Financial Planning Agent (LLM + 규칙 하이브리드)

| 항목 | 내용 |
|------|------|
| 구현 위치 | `app/agents/planner.py`(진입점+규칙), `app/agents/llm_planner.py`(LLM 루프), `app/agents/tools.py`(도구) |
| API | `POST /api/planning/{user_id}/action-plan?goal_id=` |
| 동작 방식 | `OPENAI_API_KEY` 설정 시 → **LLM tool-calling Agent** (최대 6회 도구 호출 루프) / 키 없거나 실패 시 → 규칙 기반 폴백 |
| LLM 도구 5개 | `get_profile_summary`(프로필), `get_goals_with_feasibility`(목표+가능성), `get_market_products`(실제 예·적금 상품/금리), `get_spending_alerts`(소비 알림), `get_rule_based_suggestions`(규칙 제안 참고자료) |
| 규칙 기반 | `_rule_based_actions()` — 현금보유율<20% → 예·적금 확대 / 저축률<20% → 지출 점검 / 부채비율>40% → 상환 계획 / 목표 달성 불가 → 필요 저축액 제시 |
| 출력 | Action Plan(JSON) + 추천 근거(rationale) + 예상 결과 → `action_plans` 테이블에 이력 저장 |

#### ✅ 5.5 소비 변화 모니터링

| 항목 | 내용 |
|------|------|
| 구현 위치 | `app/services/monitoring_service.py`, `app/api/monitoring.py` |
| API | `GET /api/monitoring/{user_id}/spending` |
| 감지 로직 | 이번 달 변동지출을 경과 일수로 환산한 월말 예상치 vs 직전 3개월 평균, **+15% 이상 시 warning 알림** (고정지출 제외로 왜곡 방지) |

#### ⬜ 5.6 금융 정보 변화 모니터링 (스텁)

| 항목 | 내용 |
|------|------|
| 구현 위치 | `monitoring_service.detect_market_changes()` — 빈 리스트 반환만 하는 스텁 |
| API | `GET /api/monitoring/{user_id}/market` (호출되나 항상 빈 결과) |

#### ✅ 5.7 Re-Planning Agent

| 항목 | 내용 |
|------|------|
| 구현 위치 | `app/agents/replanner.py` |
| API | `POST /api/planning/{user_id}/replan` |
| 동작 | 5.5 소비 알림 조회 → 알림 없으면 `null`(재계획 불필요), 있으면 새 Action Plan 생성 + rationale에 `[재계획 사유]` 명시 |

### 7.2 인프라 / 데이터

| 항목 | 위치 | 내용 |
|------|------|------|
| FastAPI 앱 | `app/main.py` | 라우터 5개 등록, CORS, 시작 시 DB 테이블 생성, `/health`, Swagger UI(`/docs`) |
| 환경 설정 | `app/config.py` | pydantic-settings로 `.env` 로드 (`OPENAI_API_KEY`, `LLM_MODEL`, `FSS_API_KEY`, `DATABASE_URL`) |
| ORM 엔티티 | `app/models/entities.py` | `User`(직업/페르소나 유형 포함) / `FinancialProfile` / `Goal` / `Transaction` / `ActionPlan` |
| API 스키마 | `app/models/schemas.py` | Pydantic 요청/응답 모델 (Python 3.9 호환 `Optional[]`) |
| DB 세션 | `app/db/session.py` | SQLite + SQLAlchemy, FastAPI 의존성 주입용 `get_db()` |
| 페르소나 정의 | `data/personas.json` | 사용자 3명(사회초년생 IT개발자/신혼부부 간호사/과소비형 마케터) — 이 파일만 편집하면 인물 추가 가능 |
| 마이데이터 생성 | `scripts/generate_mydata.py` | personas.json → 금융분야 마이데이터 표준 API 규격(v202102-1) 기반 업권 9종(은행/카드/금투/보험/전금/통신/IRP/할부금융/보증보험) JSON 생성 — `data/mydata/user_00X/` 각 16개 파일, 생성 시 자산 배분 정합성 자동 검증 |
| 마이데이터 어댑터 | `scripts/mydata_adapter.py` | 마이데이터 JSON → 내부 DB 모델 변환 (계좌/대출 집계, 카드 승인·이체·통신·보험료 → 거래내역) |
| DB 적재 | `scripts/seed_data.py` | 어댑터 변환 결과 → DB (`--reset` 옵션), 적재 시 personas.json 원본과 자산/부채 대조 검증 |

### 7.3 To-Do List (상세)

#### 🔴 우선순위 높음 — 핵심 기능 완성

| # | 작업 | 수정할 위치 | 상세 |
|---|------|-------------|------|
| 1 | OpenAI 실호출 테스트 | `backend/.env` 생성 | `OPENAI_API_KEY=sk-...` 등록 → LLM Agent 경로 실제 검증 (현재 폴백 경로만 검증됨) |
| 2 | 금감원 API 실연동 | `backend/.env` | [finlife.fss.or.kr](https://finlife.fss.or.kr)에서 무료 키 발급 → `FSS_API_KEY` 등록만 하면 실상품 조회됨 (코드 완성) |
| 3 | 거래내역 API | `app/api/transactions.py` 신규, `app/services/` 확장 | 거래 입력/조회, 카테고리별 소비 집계, 월별 추이 — 5.1 소비 분석 완성에 필요 |

#### 🟡 중간 우선순위 — 기능 확장

| # | 작업 | 수정할 위치 | 상세 |
|---|------|-------------|------|
| 4 | 5.6 금융 환경 변화 감지 | `monitoring_service.detect_market_changes()` | 이전 금리/상품 스냅샷을 DB에 저장 후 비교 → 기준금리 변동, 신규 고금리 상품 출시 알림 |
| 5 | 한국은행 ECOS 연동 | `market_service.get_base_rate()` | 하드코딩 2.50% → ECOS API 실제 기준금리 |
| 6 | Re-Planner에 5.6 통합 | `agents/replanner.py` | 현재 소비 알림만 트리거 → 금융 환경 알림도 재계획 사유로 추가 |
| 7 | 모니터링 스케줄러 | `app/main.py` + 신규 모듈 | APScheduler로 주기 실행 (현재는 API 호출 시에만 감지) — requirements에 포함되어 있음 |

#### 🟢 이후 단계 — Phase 2~ & UI

| # | 작업 | 수정할 위치 | 상세 |
|---|------|-------------|------|
| 8 | Phase 2 예·적금 전략 | `agents/` + `services/` 확장 | 목표 기반 상품 추천, 만기 시뮬레이션, 우대금리 분석 — LLM 도구로 추가 |
| 9 | 프론트엔드 | `frontend/` 신규 | Streamlit(빠른 데모) or React+Vite(정식) — 자산/목표/Action Plan 대시보드. CORS 이미 설정됨 |
| 10 | What-if Simulation | `agents/` 신규 도구 | "여행 가면?" 등 시나리오를 프로필에 임시 반영 후 재분석 |
| 11 | Phase 3~4 대출/투자 | `agents/`, `services/` | DSR/LTV 계산, 대출 상품 비교, 자산 배분 전략 |

#### ⚙️ 기술 부채

| 작업 | 위치 | 상세 |
|------|------|------|
| 테스트 커버리지 확대 | `tests/` | 현재 profile만 4개 — goal/monitoring/planner 테스트 추가 필요 |
| Alembic 마이그레이션 | `backend/` | 현재 `create_all` 방식 — 스키마 변경 시 DB 재생성 필요한 상태 |
| async 정리 | `agents/tools.py` | `asyncio.run()` 사용 중 — FastAPI async 컸텍스트와 충돌 가능성, 동기 함수로 정리 권장 |
| 운영 보안 | `app/main.py` | CORS `allow_origins=["*"]` 제한, 사용자 인증 도입 |

---

## 8. 코드 구조

```text
AFPA/
├── README.MD
└── backend/
    ├── requirements.txt          # 의존성 (FastAPI, SQLAlchemy, LangChain 등)
    ├── .env.example              # 환경변수 템플릿 (API 키 등)
    ├── afpa.db                   # SQLite DB (자동 생성, git 제외)
    │
    ├── app/                      # 애플리케이션 본체
    │   ├── main.py               # FastAPI 진입점 — 라우터 등록, DB 초기화
    │   ├── config.py             # 환경 설정 (pydantic-settings, .env 로드)
    │   │
    │   ├── api/                  # ── REST API 라우터 계층 ──
    │   │   ├── profile.py        # 5.1  PUT /api/profile/{user_id}, GET .../summary
    │   │   ├── goals.py          # 5.2  목표 CRUD + GET .../feasibility
    │   │   ├── market_data.py    # 5.3  GET /api/market/deposits·savings·base-rate
    │   │   ├── planning.py       # 5.4/5.7/5.8  POST .../action-plan, .../replan
    │   │   └── monitoring.py     # 5.5/5.6  GET .../spending, .../market
    │   │
    │   ├── services/             # ── 도메인 로직 계층 ──
    │   │   ├── profile_service.py     # 자산 분석, 금융 건강도 점수·등급 계산
    │   │   ├── goal_service.py        # 목표 관리, 달성 가능성 분석
    │   │   ├── market_service.py      # 금융상품/금리 수집 (금감원 API 연동 지점)
    │   │   └── monitoring_service.py  # 소비 변화 감지 (3개월 평균 대비)
    │   │
    │   ├── agents/               # ── 에이전트 계층 ──
    │   │   ├── planner.py        # 5.4/5.8 진입점 — LLM 우선, 실패 시 규칙 기반 폴백
    │   │   ├── llm_planner.py    # OpenAI tool-calling Agent 루프 (시스템 프롬프트, JSON 파싱)
    │   │   ├── tools.py          # LLM이 호출하는 도구 5개 (프로필/목표/상품/알림/규칙제안)
    │   │   └── replanner.py      # 5.7 변화 감지 → 자동 재계획
    │   │
    │   ├── models/               # ── 데이터 모델 ──
    │   │   ├── entities.py       # SQLAlchemy ORM (User/Profile/Goal/Transaction/ActionPlan)
    │   │   └── schemas.py        # Pydantic 요청/응답 스키마
    │   │
    │   └── db/
    │       └── session.py        # DB 엔진/세션 관리, 테이블 초기화
    │
    ├── data/                     # ── 테스트 데이터 ──
    │   ├── personas.json         # 페르소나 정의 (직업/유형/프로필/목표) ★ 여기를 편집해 인물 추가
    │   └── mydata/               # ↓ generate_mydata 산출물 (마이데이터 표준 API 규격 JSON)
    │       ├── user_001/         #   은행/카드/금투/보험/전금/통신/IRP/할부금융/보증보험 16개 파일
    │       ├── user_002/
    │       └── user_003/
    │
    ├── scripts/
    │   ├── generate_mydata.py    # personas.json → 마이데이터 JSON 생성 (+정합성 검증)
    │   ├── mydata_adapter.py     # 마이데이터 JSON → 내부 DB 모델 변환
    │   └── seed_data.py          # 변환 결과 → DB 적재 (--reset 옵션, +원본 대조 검증)
    │
    └── tests/
        └── test_profile_service.py  # 금융 건강도 단위 테스트
```

### 계층 구조 (요청 흐름)

```text
클라이언트
   ↓ HTTP
[api/]        라우팅·검증 (Pydantic 스키마)
   ↓
[agents/]     Action Plan 생성·재계획
   │            planner ─→ (키 있음) llm_planner ─ tool-calling ─→ tools ─→ services
   │                    └→ (키 없음/실패) 규칙 기반 폴백
[services/]   도메인 로직 (분석·계산·감지)
   ↓
[models/ + db/]  ORM 엔티티 ↔ SQLite
```

### 실행 방법

```powershell
cd D:\AFPA\backend

# 0) (선택) LLM Agent 활성화 — .env 파일 생성
#    OPENAI_API_KEY=sk-...      ← 있으면 LLM Agent, 없으면 규칙 기반
#    FSS_API_KEY=...            ← 있으면 실제 금융상품, 없으면 더미

# 1) 테스트 데이터 준비
python -m scripts.generate_mydata       # 페르소나 JSON → 마이데이터 JSON (업권 9종)
python -m scripts.seed_data --reset     # 마이데이터 → DB 적재 (정합성 검증 포함)

# 2) 서버 실행
python -m uvicorn app.main:app --reload
# → http://localhost:8000/docs (Swagger UI)

# 3) 테스트
python -m pytest tests -q
```

