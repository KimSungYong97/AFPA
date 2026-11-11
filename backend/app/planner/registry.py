"""행동 후보 공급자(provider)와 규칙 판정기(rule checker)의 등록소 — 3차 이후 도메인 모듈이 꽂히는 자리

통합 플래너는 후보의 출처를 모른다. 도메인 모듈(소비 절감·자산 조정, 3차의 예·적금, 4차의 대출·부동산, 5차의 투자)은
`CandidateProvider`를 등록해 후보를 올리고, 규제·제도 규칙 엔진은 `RuleChecker`를 등록해 "이 사용자가 실제로 할 수 있는가"를 판정한다.

후보(dict)가 지켜야 할 약속은 `candidates.make_candidate` 를 보라.
핵심은 `change` 다. 후보가 경로를 어떻게 바꾸는지를 데이터로 적어 두면(월 배분액 변화, 일회성 지출, 목표별 수익률),
순위·조합·시나리오 계산을 플래너가 도메인 모듈마다 따로 짜지 않고 한 곳에서 한다.

  change = {
      "monthly_delta": 월 여유 자금 변화(원, +는 더 모음),
      "one_offs":      {몇 개월 뒤: 추가 지출(원)},
      "goal_returns":  {목표 이름: {"annual_return": 연 수익률, "tax_rate": 세율}},   # 예: 적금으로 옮기면
  }
"""
from dataclasses import dataclass
from typing import List, Protocol


@dataclass
class Eligibility:
    ok: bool
    rule_id: str = ""            # 판정에 쓴 규칙 번호 (결정표·규칙표의 ID)
    reason: str = ""             # 사용자에게 보여 줄 이유


class CandidateProvider(Protocol):
    name: str

    def generate(self, ctx) -> List[dict]:           # ctx: candidates.CandidateContext
        ...


class RuleChecker(Protocol):
    def check(self, cand: dict, facts: dict) -> Eligibility:
        ...


_providers: List[CandidateProvider] = []
_checkers: List[RuleChecker] = []
_loaded = False


def _load_builtin() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from app.planner import builtin_providers
    _providers[:0] = [builtin_providers.SpendingProvider(), builtin_providers.AssetProvider()]


def providers() -> List[CandidateProvider]:
    _load_builtin()
    return list(_providers)


def checkers() -> List[RuleChecker]:
    return list(_checkers)


def register_provider(p: CandidateProvider) -> None:
    _load_builtin()
    if any(x.name == p.name for x in _providers):
        raise ValueError(f"이미 등록된 후보 공급자입니다: {p.name}")
    _providers.append(p)


def register_rule_checker(c: RuleChecker) -> None:
    _checkers.append(c)


def unregister_provider(name: str) -> None:
    _providers[:] = [p for p in _providers if p.name != name]


def clear_rule_checkers() -> None:
    _checkers.clear()
