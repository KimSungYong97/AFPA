# 사용자 목표 맞춤형 금융 planning

진행 상태: 계획 중
담당자: 김주영, 김성용
선행 작업: 목표 관리 (%EC%9E%91%EC%97%85%20%EC%9D%BC%EC%A0%95/%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8/%EB%AA%A9%ED%91%9C%20%EA%B4%80%EB%A6%AC%2050dcffdf2f2b83d6bbd60182c901c4e4.md)
우선순위: 높음

# 세부 기능

설계 문서: [Planning Agent 전체 설계](%EC%82%AC%EC%9A%A9%EC%9E%90%20%EB%AA%A9%ED%91%9C%20%EB%A7%9E%EC%B6%A4%ED%98%95%20%EA%B8%88%EC%9C%B5%20planning/Planning%20Agent%20%EC%A0%84%EC%B2%B4%20%EC%84%A4%EA%B3%84.md)

구현 순서: **2차(통합 플래너)부터 차수별 확장** — 기준: [AFPA 로드맵 및 구현 순서](../../%EA%B3%B5%ED%86%B5%20%EC%84%A4%EA%B3%84/AFPA%20%EB%A1%9C%EB%93%9C%EB%A7%B5%20%EB%B0%8F%20%EA%B5%AC%ED%98%84%20%EC%88%9C%EC%84%9C.md)

## ✅ Planning Agent 전체 설계

: 현재 금융 상태와 목표를 분석하여 목표 달성을 위한 실행 가능한 금융 전략(Action Plan) 생성

### 입력

- **사용자 정보:** 금융 프로필, 목표, Life Event
- **외부 정보:** 금융상품 정보, 금융 정책 및 규제, 금리 정보

### 구성 (구현 순서)

- 1차: 기본 분석 (플랫폼 기능)
- 2차: **통합 플래너** (경로·시나리오·Action Plan·이행 추적)
- 3차: 규제·제도 엔진 + 예·적금
- 4차: 대출·부동산
- 5차: 투자
- 6차: 자율성 고도화

## ✅ 출력 형식

- **Action Plan:** 사용자의 목표 달성을 위한 실행 가능한 금융 전략
- **추천 근거:** 추천 이유, 사용자 상황 기반 분석, 금융상품 비교, 정책·규제 반영 내용

※ 단계별 세부 기능은 planning-1차 ~ 6차 프로젝트에서 관리

## 작업

[Tasks](%EC%82%AC%EC%9A%A9%EC%9E%90%20%EB%AA%A9%ED%91%9C%20%EB%A7%9E%EC%B6%A4%ED%98%95%20%EA%B8%88%EC%9C%B5%20planning/Tasks%203accffdf2f2b809280c9f6d4d83f4b31.csv)