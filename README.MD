# 🤖 AI Financial Planning Agent (AFPA)

> 사용자의 목표를 기준으로 저축·대출·투자·부동산을 **하나의 경로로 통합 설계**하고, **목표를 가장 빨리 이루는 행동을 순위로 알려주는** 금융 관리 agent

---

## 1. 프로젝트 개요

### 1.1 무엇을 만드는가
사용자의 목표를 기준으로 저축·대출·투자·부동산을 하나의 경로로 통합 설계하고, 사용자 데이터와 규제·제도를 반영해 목표를 가장 빨리 이루는 행동을 순위로 제시하며, 상황이 바뀌면 스스로 갱신하는 금융 관리 agent.

### 1.2 해결하려는 문제

| 문제 | 설명 |
|------|------|
| 진단 | 자산·소비 정보가 여러 금융사에 흩어져 있어 재무 상태를 한눈에 파악하기 어렵다 |
| 계획 | 목표에 대해 "얼마를, 언제까지, 어떻게" 모아야 하는지가 구체적 행동으로 연결되지 않는다 |
| 통합 | 예·적금, 대출, 투자, 부동산 의사결정이 서로 영향을 주는데 기존 서비스는 도메인별로 따로 다룬다 |
| 제도 | 대출 규제, 자격 요건, 세제 혜택처럼 실제로 받을 수 있는 것을 일반 사용자가 판단하기 어렵다 |
| 지속 | 계획을 세워도 실행 여부가 추적되지 않고, 상황이 바뀌어도 갱신되지 않는다 |

### 1.3 핵심 가치

| 가치 | 설명 |
|------|------|
| **목표 단축 행동 순위** (대표) | 새는 돈을 줄이는 행동과 놓친 혜택을 챙기는 행동을 "목표 달성이 N개월 빨라지는 순서"로 정렬해 효과 크기와 함께 제시 |
| 통합 자산 성장 설계 | 저축·대출·부동산·투자를 하나의 목표 아래 한 경로로 설계 |
| 경로와 시나리오 | 순자산이 어떻게 늘어나는지 보여 주고 What-if로 비교 |
| 규제·제도 반영 | 대출 한도, 가입 가능 상품, 세제 혜택을 규칙으로 판정해 실행 가능한 선택지만 제시 |
| 부동산 목표 설계 | 구매력, 전세·월세·매매 비교, 취득 비용, 청약·정책 상품 |
| 이행 추적과 갱신 | 제안의 실행 여부를 추적하고 경로 이탈 시 재계산·재제안 (승인 후 적용) |
| 선제적 관리 | 사용자가 묻기 전에 기회·위험·시점을 찾아 제안 |

### 1.4 사용자가 경험하는 모습
- **홈 = 브리핑:** 지금 가장 효과가 큰 행동을 효과 크기와 근거와 함께 순서대로 보여 준다.
- **상세 = 펼치기:** 항목을 누르면 해당 도메인의 상세가 열린다.
- **갱신 = 보고:** 변화가 생기면 관리자가 영향과 제안을 묶어 보고하고, 사용자는 승인·거절만 한다.

### 1.5 참여자

| 이름 | 역할 |
|------|------|
| 김주영 | 팀장 |
| 김성용 | 개발 |

---

## 2. 구조

```text
                          사용자 (보고받고 승인/거절)
                                   ▲  ▼
        ┌───────────────────────────────────────────────┐
        │                관리자 agent                      │
        │  브리핑·대화 층 (LLM: 선택·설명·질문 해석)          │
        │  통합 플래너 (코드: 경로·시나리오·후보 순위·이행 추적)  │
        └──────┬─────────────────────────┬───────────────┘
      후보·선택지│                          │ 가능 여부 판정
   ┌───────────┴──────────────┐   ┌──────┴─────────────────────┐
   │ 소비 절감 · 예·적금          │   │ 규제·제도 규칙 엔진            │
   │ 대출·부동산 · 투자           │   └────────────────────────────┘
   └───────────▲──────────────┘
               │ 상태: 사용자 금융 프로필 · 목표 관리 · 외부 정보 수집
               │ 관찰: 소비 변화 / 환경 변화 모니터링 → 재설계
```

- **관리자 agent** = 통합 플래너(결정적 계획 엔진) + 브리핑·대화 층(LLM). 사용자와 닿는 유일한 면이다.
- **하위 모듈**은 결정적 모듈(도구)이며, 각자 행동 후보를 올리면 관리자가 모아 순위를 매긴다.
- **동작 루프:** 관찰 → 평가(후보 계산·순위) → 제안(브리핑) → 승인 → 이행 확인 → 상태 갱신 → 관찰

### 코드와 LLM의 역할 원칙
**틀렸을 때 사용자에게 금전적 피해가 가는 결정은 코드가 하고, 되돌릴 수 있는 결정만 LLM이 한다.**
- **코드:** 모든 금액·비율 계산, 경로·시나리오, 규제·자격·세제 판정, 후보 순위
- **LLM:** 검증된 후보 중 선택·묶기, 설명 문구, 질문 의도 해석, 분류 보조, 비정형 정보의 후보 추출
- LLM은 후보(상품·자격·숫자)를 만들지 않으며, 출력 수치는 코드 결과와 일치해야 한다.
- 실제 금융 행위(이체·가입·해지·매매)는 agent가 직접 하지 않는다. 개별 종목은 추천하지 않는다.

---

## 3. 구현 순서

차수는 **구현 순서**이며 별도의 의미는 없다.

| 차수 | 이름 | 핵심 내용 |
|------|------|-----------|
| **1차** | 기본 플랫폼 | 마이데이터 연동, 자동 분류, 금융 프로필, 수입·지출·자산 분석, 목표 관리 |
| **2차** | 통합 플래너 | 자산 성장 경로, 시나리오, 행동 후보 순위, Action Plan, 이행 추적, 소비 변화 모니터링, 단순 재설계 |
| **3차** | 규제·제도 엔진 + 예·적금 | 규칙표, 외부 정보 수집, 기회 발굴, 예·적금 전략, 환경 변화 모니터링 |
| **4차** | 대출·부동산 | 구매력 분석, 전세·월세·매매 비교, 대출 전략, 청약 |
| **5차** | 투자 | 투자 성향, 자산 배분, 연금·절세 포트폴리오 |
| **6차** | 자율성 고도화 | 선제 제안, 자율 수준 설정, 개인화 |

**순서의 이유**
- 1차는 기본 금융 플랫폼 수준의 기능이며, 본격적인 agent는 2차부터 시작한다.
- 2차 통합 플래너는 외부 데이터 없이 만들 수 있고, 이후 모든 도메인이 이 위에 얹힌다.
- 3차 규칙 엔진은 대출·부동산의 전제다. 외부 수집 파이프라인은 가장 단순한 예·적금으로 먼저 검증한다.
- 부동산(4차)은 "내 집 마련"이 대표 목표라 투자(5차)보다 앞선다. 투자는 규제 부담이 가장 크다.
- 6차 자율성은 앞 차수의 이행 추적·환경 변화 알림을 묶어 완성하는 별도 단계다.

---

## 4. 기능별 역할

| 기능 | 차수 | 역할 |
|------|------|------|
| 사용자 금융 프로필 | 1차 | 마이데이터와 온보딩 정보로 현재 재무 상태를 파악하고 모든 모듈의 기본 정보를 제공한다 (분류, 지표 산출, 건강도·잠재력 점수, 이력 저장) |
| 목표 관리 | 1차 | 목표(일반·Life Event·부동산)를 등록·관리하고 달성 가능성과 부족 자금을 계산한다. 모든 후보의 평가 기준이 된다 |
| 통합 플래너 | 2차 | 관리자 agent의 계산 엔진. 경로·시나리오를 계산하고 후보를 목표 단축 기간으로 순위화하며 Action Plan과 이행 추적을 담당한다 |
| 소비 변화 모니터링 | 2차 | 소비 패턴의 구조적 변화를 감지해 알림·재설계의 계기로 삼고 소비 절감 후보를 공급한다 |
| 규제·제도 규칙 엔진 | 3차 | 대출 한도, 가입 자격, 세제 혜택을 규칙표로 판정한다. 모든 도메인이 "이 사용자가 실제로 할 수 있는가"를 여기에 묻는다 |
| 금융 정보 수집 | 3차~ | 외부 상품·정책·시장 정보를 수집·정규화하고 변경 이력을 남긴다 |
| 예·적금 | 3차 | 사용자에게 맞는 상품을 비교·추천하고 놓친 혜택을 행동 후보로 올린다 |
| 금융 환경 변화 모니터링 | 3차 | 금리·상품·정책·규칙의 변경을 감지하고 사용자 영향을 계산한다 |
| 계획 재설계 | 3차 | 모니터링 결과와 이행 이탈을 반영해 계획을 다시 만들고 변경 전후를 비교해 승인을 받는다 |
| 대출·부동산 | 4차 | 내 집 마련 중심으로 구매력, 거래 형태 비교, 대출 전략, 청약을 설계하고 대출 비용 절감 후보를 올린다 |
| 투자 | 5차 | 투자 성향에 맞는 자산 배분과 절세 포트폴리오를 제시한다 |
| 자율성 | 6차 | 묻기 전에 기회·위험·시점을 제안하고, 이행 이력으로 제안 방식을 개인화하며, 자율 수준을 사용자가 정한다 |

---

## 5. 공통 원칙

| 항목 | 원칙 |
|------|------|
| 설명 가능성 | 모든 제안에 이유·사용자 수치·적용 규칙·기준일을 함께 제공 |
| 승인 | 계획 변경은 사용자 승인 후에만 적용 |
| 개인정보 | 최소 수집, 항목별 동의, 식별 정보는 LLM에 전달하지 않음, 연동 해지 시 삭제 |
| 알림 | 유형·우선순위·빈도 제한으로 알림 피로도 관리 |
| 평가 | 계산은 골든 케이스(오차 0), 분류·순위·규칙은 테스트 데이터로 검증 |

---

## 6. 상세 설계 문서

세부 설계는 `notion/금융아빠(AFPA)/`에 있다.

| 문서 | 내용 |
|------|------|
| `AFPA 프로젝트 개요 및 전체 설계.md` | 전체 설계 총괄 |
| `공통 설계/AFPA 로드맵 및 구현 순서.md` | 구현 순서·범위 기준 |
| `공통 설계/` 나머지 | 규칙 엔진, 알림, 개인정보, LLM 원칙, 평가, 설계 파라미터 |
| `작업 일정/프로젝트/` | 기능별 상세 설계 |

---

## 7. 구현 현황 (2026-08-04 기준)

> 아래 구현 현황은 새 설계(1~6차) 이전에 만든 프로토타입 기준이다. 대략 1차 기본 플랫폼 + 2차 일부(Action Plan·재계획)에 해당하며, 통합 플래너·규칙 엔진·행동 후보 순위는 아직 구현되지 않았다.

### 7.1 서비스별 구현 상세

#### ✅ 사용자 금융 프로필 (1차)

| 항목 | 내용 |
|------|------|
| 구현 위치 | `app/services/profile_service.py`, `app/api/profile.py` |
| API | `PUT /api/profile/{user_id}` (등록/수정), `GET /api/profile/{user_id}/summary` (요약) |
| 구현 기능 | 총자산/순자산/월 여유자금 계산, 저축률·부채비율·현금보유율 산출 |
| 건강도 점수 | `_calc_health_score()` — 저축률 40점(30% 이상 만점) + 부채비율 30점(0% 만점) + 비상금 30점(월지출 6개월치 만점) = 0~100점, A~E 등급 |
| 테스트 | `tests/test_profile_service.py` (4개 통과) |

#### ✅ 목표 관리

| 항목 | 내용 |
|------|------|
| 구현 위치 | `app/services/goal_service.py`, `app/api/goals.py` |
| API | 목표 CRUD (`POST/GET/PUT/DELETE`), `GET /api/goals/item/{goal_id}/feasibility` |
| 달성 가능성 분석 | `analyze_feasibility()` — 부족 자금, 목표일 기준 필요 월 저축액, 현재 여유자금 기준 예상 달성 시기, 달성 가능 여부 판정 |

#### 🔶 금융 정보 수집 (부분 — API 키 미설정 시 더미)

| 항목 | 내용 |
|------|------|
| 구현 위치 | `app/services/market_service.py`, `app/api/market_data.py` |
| API | `GET /api/market/deposits`, `GET /api/market/savings`, `GET /api/market/base-rate` |
| 구현 상태 | 금감원(FSS) 금융상품 API 호출 코드 완성. `.env`의 `FSS_API_KEY` 미설정 시 더미 상품 반환 |
| 미구현 | 한국은행 ECOS 기준금리(하드코딩 2.50%), 정책 정보 수집 |

#### ✅ Financial Planning Agent (LLM + 규칙 하이브리드)

| 항목 | 내용 |
|------|------|
| 구현 위치 | `app/agents/planner.py`(진입점+규칙), `app/agents/llm_planner.py`(LLM 루프), `app/agents/tools.py`(도구) |
| API | `POST /api/planning/{user_id}/action-plan?goal_id=` |
| 동작 방식 | `OPENAI_API_KEY` 설정 시 → **LLM tool-calling Agent** (최대 6회 도구 호출 루프) / 키 없거나 실패 시 → 규칙 기반 폴백 |
| LLM 도구 5개 | `get_profile_summary`(프로필), `get_goals_with_feasibility`(목표+가능성), `get_market_products`(실제 예·적금 상품/금리), `get_spending_alerts`(소비 알림), `get_rule_based_suggestions`(규칙 제안 참고자료) |
| 규칙 기반 | `_rule_based_actions()` — 현금보유율<20% → 예·적금 확대 / 저축률<20% → 지출 점검 / 부채비율>40% → 상환 계획 / 목표 달성 불가 → 필요 저축액 제시 |
| 출력 | Action Plan(JSON) + 추천 근거(rationale) + 예상 결과 → `action_plans` 테이블에 이력 저장 |

#### ✅ 소비 변화 모니터링

| 항목 | 내용 |
|------|------|
| 구현 위치 | `app/services/monitoring_service.py`, `app/api/monitoring.py` |
| API | `GET /api/monitoring/{user_id}/spending` |
| 감지 로직 | 이번 달 변동지출을 경과 일수로 환산한 월말 예상치 vs 직전 3개월 평균, **+15% 이상 시 warning 알림** (고정지출 제외로 왜곡 방지) |

#### ⬜ 금융 정보 변화 모니터링 (스텁)

| 항목 | 내용 |
|------|------|
| 구현 위치 | `monitoring_service.detect_market_changes()` — 빈 리스트 반환만 하는 스텁 |
| API | `GET /api/monitoring/{user_id}/market` (호출되나 항상 빈 결과) |

#### ✅ Re-Planning Agent

| 항목 | 내용 |
|------|------|
| 구현 위치 | `app/agents/replanner.py` |
| API | `POST /api/planning/{user_id}/replan` |
| 동작 | 소비 알림 조회 → 알림 없으면 `null`(재계획 불필요), 있으면 새 Action Plan 생성 + rationale에 `[재계획 사유]` 명시 |

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
| 3 | 거래내역 API | `app/api/transactions.py` 신규, `app/services/` 확장 | 거래 입력/조회, 카테고리별 소비 집계, 월별 추이 — 소비 분석 완성에 필요 |

#### 🟡 중간 우선순위 — 기능 확장

| # | 작업 | 수정할 위치 | 상세 |
|---|------|-------------|------|
| 4 | 금융 환경 변화 감지 | `monitoring_service.detect_market_changes()` | 이전 금리/상품 스냅샷을 DB에 저장 후 비교 → 기준금리 변동, 신규 고금리 상품 출시 알림 |
| 5 | 한국은행 ECOS 연동 | `market_service.get_base_rate()` | 하드코딩 2.50% → ECOS API 실제 기준금리 |
| 6 | Re-Planner에 통합 | `agents/replanner.py` | 현재 소비 알림만 트리거 → 금융 환경 알림도 재계획 사유로 추가 |
| 7 | 모니터링 스케줄러 | `app/main.py` + 신규 모듈 | APScheduler로 주기 실행 (현재는 API 호출 시에만 감지) — requirements에 포함되어 있음 |

#### 🟢 이후 단계 — 3차~ & UI

| # | 작업 | 수정할 위치 | 상세 |
|---|------|-------------|------|
| 8 | 3차 예·적금 전략 | `agents/` + `services/` 확장 | 목표 기반 상품 추천, 만기 시뮬레이션, 우대금리 분석 — LLM 도구로 추가 |
| 9 | 프론트엔드 | `frontend/` 신규 | Streamlit(빠른 데모) or React+Vite(정식) — 자산/목표/Action Plan 대시보드. CORS 이미 설정됨 |
| 10 | 2차 What-if Simulation | `agents/` 신규 도구 | "여행 가면?" 등 시나리오를 프로필에 임시 반영 후 재분석 |
| 11 | 4~5차 대출·부동산/투자 | `agents/`, `services/` | DSR/LTV 계산, 대출 상품 비교, 자산 배분 전략 |

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
    │   │   ├── profile.py        # PUT /api/profile/{user_id}, GET .../summary
    │   │   ├── goals.py          # 목표 CRUD + GET .../feasibility
    │   │   ├── market_data.py    # GET /api/market/deposits·savings·base-rate
    │   │   ├── planning.py       # POST .../action-plan, .../replan
    │   │   └── monitoring.py     # GET .../spending, .../market
    │   │
    │   ├── services/             # ── 도메인 로직 계층 ──
    │   │   ├── profile_service.py     # 자산 분석, 금융 건강도 점수·등급 계산
    │   │   ├── goal_service.py        # 목표 관리, 달성 가능성 분석
    │   │   ├── market_service.py      # 금융상품/금리 수집 (금감원 API 연동 지점)
    │   │   └── monitoring_service.py  # 소비 변화 감지 (3개월 평균 대비)
    │   │
    │   ├── agents/               # ── 에이전트 계층 ──
    │   │   ├── planner.py        # 진입점 — LLM 우선, 실패 시 규칙 기반 폴백
    │   │   ├── llm_planner.py    # OpenAI tool-calling Agent 루프 (시스템 프롬프트, JSON 파싱)
    │   │   ├── tools.py          # LLM이 호출하는 도구 5개 (프로필/목표/상품/알림/규칙제안)
    │   │   └── replanner.py      # 변화 감지 → 자동 재계획
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

