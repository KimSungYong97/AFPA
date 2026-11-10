# 사용자 목표 맞춤형 금융 planning-3차

진행 상태: 계획 중
담당자: 김주영, 김성용
선행 작업: 사용자 목표 관련 금융 정보 수집 (%EC%9E%91%EC%97%85%20%EC%9D%BC%EC%A0%95/%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8/%EC%82%AC%EC%9A%A9%EC%9E%90%20%EB%AA%A9%ED%91%9C%20%EA%B4%80%EB%A0%A8%20%EA%B8%88%EC%9C%B5%20%EC%A0%95%EB%B3%B4%20%EC%88%98%EC%A7%91%203accffdf2f2b809b9c4be16b1189d464.md)
후속 작업: 금융관련 정보 변화 모니터링 (%EC%9E%91%EC%97%85%20%EC%9D%BC%EC%A0%95/%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8/%EA%B8%88%EC%9C%B5%EA%B4%80%EB%A0%A8%20%EC%A0%95%EB%B3%B4%20%EB%B3%80%ED%99%94%20%EB%AA%A8%EB%8B%88%ED%84%B0%EB%A7%81%203accffdf2f2b8070a9d6c711df5670ee.md), 사용자 목표 맞춤형 금융 planning-4차 (%EC%9E%91%EC%97%85%20%EC%9D%BC%EC%A0%95/%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8/%EC%82%AC%EC%9A%A9%EC%9E%90%20%EB%AA%A9%ED%91%9C%20%EB%A7%9E%EC%B6%A4%ED%98%95%20%EA%B8%88%EC%9C%B5%20planning-4%EC%B0%A8%203accffdf2f2b806ea685fc3aadc89b08.md)
우선순위: 높음

# 세부 기능

설계 문서: [3차 규제·제도 엔진 및 예·적금 설계](%EC%82%AC%EC%9A%A9%EC%9E%90%20%EB%AA%A9%ED%91%9C%20%EB%A7%9E%EC%B6%A4%ED%98%95%20%EA%B8%88%EC%9C%B5%20planning-3%EC%B0%A8/3%EC%B0%A8%20%EA%B7%9C%EC%A0%9C%C2%B7%EC%A0%9C%EB%8F%84%20%EC%97%94%EC%A7%84%20%EB%B0%8F%20%EC%98%88%C2%B7%EC%A0%81%EA%B8%88%20%EC%84%A4%EA%B3%84.md)

구현 순서: **3차 (규칙 엔진 + 예·적금)** — 기준: [AFPA 로드맵 및 구현 순서](../../%EA%B3%B5%ED%86%B5%20%EC%84%A4%EA%B3%84/AFPA%20%EB%A1%9C%EB%93%9C%EB%A7%B5%20%EB%B0%8F%20%EA%B5%AC%ED%98%84%20%EC%88%9C%EC%84%9C.md)

## ✅ 규제·제도 규칙 엔진

- 대출 규제(DSR/LTV), 자격 요건, 세제 규칙표
- 판정 함수와 근거(규칙 ID·기준일) 출력
- 문서: 공통 설계/규제·제도 규칙 엔진 설계

## ✅ 예·적금 모듈

- 예·적금 추천, 금리·우대금리 비교, 만기 시뮬레이션, 리밸런싱
- 통합 플래너의 선택지로 연결(목표 달성 시기 변화)

## ✅ 세제 연계

- ISA·IRP·연금저축 활용 여력, 세후 효과

## ✅ 마이데이터 확장

- 대출 정보 수집 추가(DSR 계산용), 부채 분류 활성화

## 작업

[Tasks](%EC%82%AC%EC%9A%A9%EC%9E%90%20%EB%AA%A9%ED%91%9C%20%EB%A7%9E%EC%B6%A4%ED%98%95%20%EA%B8%88%EC%9C%B5%20planning-3%EC%B0%A8/Tasks%203accffdf2f2b80d28ab7dffbdc0388a5.csv)
