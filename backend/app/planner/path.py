"""자산 성장 경로 엔진 (결정적 월 단위 시뮬레이션)

- 월 여유 자금(budget)을 우선순위 순으로 목표에 배분한다.
    1차 배분: 기한이 있는 목표에 "남은 금액 / 남은 개월 수"(필요 월 저축액)를 우선순위 순으로 채운다.
    2차 배분: 남는 돈은 우선순위가 높은 미완료 목표부터 채워 달성을 앞당긴다.
    목표가 끝나면 그 몫이 다음 목표로 이어진다.
- 적립 모델: 월 납입 누적 + 단순 수익률 가정(월복리, 보수적 기본값).
- 월 여유 자금이 음수인 달은 우선순위가 낮은 목표의 적립금부터 인출해 메운다.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

from app.pipeline import params


# ---------------------------------------------------------------------------
# 입력 / 출력
# ---------------------------------------------------------------------------
@dataclass
class PathGoal:
    name: str
    target_amount: float
    current_amount: float = 0.0
    target_date: Optional[date] = None
    priority: int = 1


@dataclass
class PathInput:
    as_of: date
    monthly_budget: float                       # 월 여유 자금
    goals: List[PathGoal]
    annual_return: float = params.RETURN_ASSUMPTIONS[params.DEFAULT_RETURN_CASE]
    initial_net_worth: float = 0.0
    one_offs: Dict[int, float] = field(default_factory=dict)   # {몇 개월 뒤: 추가 지출액}
    horizon_months: int = params.PATH_HORIZON_MONTHS


@dataclass
class GoalPath:
    name: str
    priority: int
    target_amount: float
    start_amount: float
    target_date: Optional[date]
    deadline_k: Optional[int]                   # 기한까지 남은 개월 수 (as_of 기준)
    required_monthly: Optional[float]           # 시작 시점의 필요 월 저축액
    first_month_alloc: float
    completion_k: Optional[int]                 # 달성까지 걸리는 개월 수 (None = 기간 내 달성 불가)
    completion_date: Optional[date]
    gap_months: Optional[int]                   # 달성 시기 − 기한 (양수 = 지연, 음수 = 앞당김)
    balance_at_deadline: Optional[float]
    shortfall_at_deadline: Optional[float]
    status: str                                 # done | on_track | late | unreachable | no_deadline


@dataclass
class PathResult:
    goals: List[GoalPath]
    series: List[dict]                          # [{k, date, net_worth, balances{name: 금액}}]
    free_savings_end: float
    horizon: int

    def goal(self, name: str) -> Optional[GoalPath]:
        return next((g for g in self.goals if g.name == name), None)


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------
def add_months(d: date, k: int) -> date:
    y, m = divmod(d.year * 12 + (d.month - 1) + k, 12)
    m += 1
    import calendar
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


# ---------------------------------------------------------------------------
# 시뮬레이션
# ---------------------------------------------------------------------------
def simulate(inp: PathInput, series_months: int = params.SERIES_MONTHS) -> PathResult:
    r_m = (1 + inp.annual_return) ** (1 / 12) - 1
    goals = sorted(inp.goals, key=lambda g: g.priority)
    n = len(goals)

    bal = [g.current_amount for g in goals]
    done_k: List[Optional[int]] = [0 if g.current_amount >= g.target_amount else None for g in goals]
    deadline_k = [months_between(inp.as_of, g.target_date) if g.target_date else None for g in goals]
    bal_at_deadline: List[Optional[float]] = [None] * n
    first_alloc = [0.0] * n
    required0: List[Optional[float]] = [None] * n
    for i, g in enumerate(goals):
        if deadline_k[i] is not None:
            remaining = max(g.target_amount - g.current_amount, 0.0)
            required0[i] = remaining / max(deadline_k[i], 1) if remaining > 0 else 0.0
        if deadline_k[i] is not None and deadline_k[i] <= 0:
            bal_at_deadline[i] = bal[i]

    base_nw = inp.initial_net_worth
    free = 0.0
    series: List[dict] = [{"k": 0, "date": inp.as_of, "net_worth": base_nw,
                           "balances": {g.name: bal[i] for i, g in enumerate(goals)}}]
    start_total = sum(bal)

    horizon = inp.horizon_months
    for k in range(1, horizon + 1):
        # 1) 수익률 반영 (미완료 목표만)
        for i in range(n):
            if done_k[i] is None and bal[i] > 0:
                bal[i] *= (1 + r_m)
        free *= (1 + r_m)

        # 2) 이번 달 가용 금액
        budget = inp.monthly_budget - inp.one_offs.get(k, 0.0)
        if budget < 0:
            need = -budget
            for i in reversed(range(n)):          # 우선순위가 낮은 목표부터 인출
                take = min(need, bal[i]) if done_k[i] is None else 0.0
                bal[i] -= take
                need -= take
            if need > 0:
                free -= need                       # 목표 적립금으로도 부족하면 자유 저축에서 차감(음수 가능)
            budget = 0.0

        # 3) 1차 배분: 기한 있는 목표의 필요 월 저축액 (우선순위 순)
        left = budget
        for i in range(n):
            if done_k[i] is not None or deadline_k[i] is None or left <= 0:
                continue
            remaining = max(goals[i].target_amount - bal[i], 0.0)
            months_left = max(deadline_k[i] - (k - 1), 1)
            need = remaining if deadline_k[i] < k else remaining / months_left
            alloc = min(left, need)
            bal[i] += alloc
            left -= alloc
            if k == 1:
                first_alloc[i] += alloc
        # 4) 2차 배분: 남는 돈은 우선순위 순으로 미완료 목표에
        for i in range(n):
            if done_k[i] is not None or left <= 0:
                continue
            remaining = max(goals[i].target_amount - bal[i], 0.0)
            alloc = min(left, remaining)
            bal[i] += alloc
            left -= alloc
            if k == 1:
                first_alloc[i] += alloc
        free += left                               # 모든 목표를 채우고도 남는 돈

        # 5) 달성 판정 / 기한 시점 잔액 기록
        for i in range(n):
            if done_k[i] is None and bal[i] >= goals[i].target_amount - 1e-6:
                bal[i] = goals[i].target_amount
                done_k[i] = k
            if deadline_k[i] is not None and k == deadline_k[i]:
                bal_at_deadline[i] = bal[i]

        if k <= series_months:
            series.append({
                "k": k, "date": add_months(inp.as_of, k),
                "net_worth": base_nw + (sum(bal) - start_total) + free,
                "balances": {g.name: bal[i] for i, g in enumerate(goals)},
            })

        # 모든 목표가 끝났고 기한도 지났으면 더 돌릴 필요가 없다
        if all(d is not None for d in done_k) and all((dk is None or k >= dk) for dk in deadline_k):
            break

    paths: List[GoalPath] = []
    for i, g in enumerate(goals):
        ck = done_k[i]
        dk = deadline_k[i]
        gap = (ck - dk) if (ck is not None and dk is not None) else None
        bd = bal_at_deadline[i]
        shortfall = None
        if dk is not None:
            if ck is not None and ck <= max(dk, 0):
                shortfall = 0.0
            else:
                shortfall = max(g.target_amount - (bd if bd is not None else bal[i]), 0.0)
        if ck is not None and ck == 0:
            status = "done"
        elif ck is None:
            status = "unreachable"
        elif dk is None:
            status = "no_deadline"
        else:
            status = "on_track" if ck <= dk else "late"
        paths.append(GoalPath(
            name=g.name, priority=g.priority, target_amount=g.target_amount, start_amount=g.current_amount,
            target_date=g.target_date, deadline_k=dk, required_monthly=required0[i],
            first_month_alloc=first_alloc[i], completion_k=ck,
            completion_date=add_months(inp.as_of, ck) if ck is not None else None,
            gap_months=gap, balance_at_deadline=bd, shortfall_at_deadline=shortfall, status=status,
        ))
    return PathResult(goals=paths, series=series, free_savings_end=free, horizon=horizon)


# ---------------------------------------------------------------------------
# 효과 비교 (후보·시나리오 공통)
# ---------------------------------------------------------------------------
def compare(base: PathResult, other: PathResult) -> List[dict]:
    """목표별 기준 경로 대비 차이. months_saved > 0 이면 앞당겨짐."""
    out = []
    for b in base.goals:
        o = other.goal(b.name)
        if o is None:
            continue
        if b.completion_k is not None and o.completion_k is not None:
            saved: Optional[int] = b.completion_k - o.completion_k
            reach = False
        else:
            saved = None
            reach = b.completion_k is None and o.completion_k is not None
        out.append({
            "goal": b.name,
            "base_completion": b.completion_date, "new_completion": o.completion_date,
            "base_k": b.completion_k, "new_k": o.completion_k,
            "months_saved": saved, "makes_reachable": reach,
            "becomes_unreachable": b.completion_k is not None and o.completion_k is None,
            "shortfall_change": (None if b.shortfall_at_deadline is None or o.shortfall_at_deadline is None
                                 else o.shortfall_at_deadline - b.shortfall_at_deadline),
        })
    return out


def net_worth_at(result: PathResult, k: int) -> Optional[float]:
    row = next((s for s in result.series if s["k"] == k), None)
    if row is None and result.series:
        row = result.series[-1] if k > result.series[-1]["k"] else None
    return None if row is None else row["net_worth"]


def with_budget(inp: PathInput, delta: float) -> PathInput:
    c = deepcopy(inp)
    c.monthly_budget += delta
    return c
