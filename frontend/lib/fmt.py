"""숫자·날짜·지표를 사람이 읽는 말로 바꾸는 함수들"""
from datetime import date
from typing import Optional


def josa(word: str, with_batchim: str, without_batchim: str) -> str:
    """받침 유무에 따라 조사만 돌려준다. josa('마련', '은', '는') → '은'"""
    if not word:
        return without_batchim
    code = ord(word[-1])
    if 0xAC00 <= code <= 0xD7A3:
        return with_batchim if (code - 0xAC00) % 28 else without_batchim
    return without_batchim


def won(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:,.0f}원"


def short_won(x: Optional[float]) -> str:
    """큰 금액은 '억/만 원'으로 줄여서 보여 준다"""
    if x is None:
        return "-"
    sign = "-" if x < 0 else ""
    a = abs(x)
    if a >= 100_000_000:
        v = f"{a / 100_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{sign}{v}억 원"
    if a >= 10_000:
        return f"{sign}{a / 10_000:,.0f}만 원"
    return f"{sign}{a:,.0f}원"


def ym(iso: Optional[str]) -> str:
    """'2029-02-07' → '2029년 2월'"""
    if not iso:
        return "-"
    d = date.fromisoformat(iso[:10])
    return f"{d.year}년 {d.month}월"


def months_text(n: Optional[float]) -> str:
    """15 → '1년 3개월', 3 → '3개월'"""
    if n is None:
        return "-"
    n = abs(int(round(n)))
    y, m = divmod(n, 12)
    if y and m:
        return f"{y}년 {m}개월"
    if y:
        return f"{y}년"
    return f"{m}개월"


def pct(x: Optional[float], digits: int = 0) -> str:
    return "-" if x is None else f"{x:.{digits}f}%"


# ---------------------------------------------------------------------------
# 점수 해설
# ---------------------------------------------------------------------------
def health_words(score: Optional[float]) -> tuple:
    """(한 줄 평가, 색 tone)"""
    if score is None:
        return "아직 계산할 수 없어요", "gray"
    if score >= 80:
        return "아주 좋아요", "good"
    if score >= 60:
        return "좋은 편이에요", "good"
    if score >= 40:
        return "보통이에요. 개선할 여지가 있어요", "warn"
    if score >= 20:
        return "주의가 필요해요", "bad"
    return "많이 위험해요", "bad"


def level_words(ratio: Optional[float]) -> tuple:
    """항목별 득점 비율(0~1) → (말, tone)"""
    if ratio is None:
        return "-", "gray"
    if ratio >= 0.9:
        return "충분해요", "good"
    if ratio >= 0.6:
        return "괜찮아요", "good"
    if ratio >= 0.3:
        return "조금 부족해요", "warn"
    return "많이 부족해요", "bad"


def effect_text(e: dict, mandatory: bool = False) -> tuple:
    """경로 효과를 한 문장으로. (문장, tone)"""
    if e.get("makes_reachable"):
        return "목표를 달성할 수 있게 돼요", "good"
    ms = e.get("months_saved")
    if ms is not None and ms > 0:
        return f"목표가 {months_text(ms)} 빨라져요", "good"
    if ms is not None and ms < 0:
        return f"목표가 {months_text(ms)} 늦어지지만 먼저 필요해요" if mandatory else f"목표가 {months_text(ms)} 늦어져요", "warn"
    if e.get("deficit_closed_pct"):
        return f"매달 적자의 {e['deficit_closed_pct']:.0f}%를 메워요", "good"
    annual = e.get("annual_saving") or 0
    return (f"1년에 {short_won(annual)} 아껴요", "info") if annual else ("먼저 해야 해요", "warn")


GOAL_STATUS = {
    "done": ("달성 완료", "good"),
    "on_track": ("기한 안에 달성해요", "good"),
    "late": ("기한보다 늦어요", "warn"),
    "unreachable": ("지금은 달성이 어려워요", "bad"),
    "no_deadline": ("기한 없는 목표", "info"),
}


def goal_sentence(g: dict) -> str:
    """목표 경로를 한 문장으로"""
    st_ = g["status"]
    if st_ == "done":
        return "이미 목표 금액을 모았어요."
    if st_ == "unreachable":
        return "지금처럼 모으면 오랫동안 달성하기 어려워요."
    when = ym(g["completion_date"])
    gap = g.get("gap_months")
    if gap is None:
        return f"지금 속도면 {when}쯤 달성해요."
    if gap > 0:
        return f"지금 속도면 {when}쯤 달성해요. 기한보다 {months_text(gap)} 늦어요."
    if gap < 0:
        return f"지금 속도면 {when}쯤 달성해요. 기한보다 {months_text(gap)} 일찍 끝나요."
    return f"지금 속도면 기한에 맞춰 {when}쯤 달성해요."


def goal_gap_text(g: dict) -> str:
    """카드용 짧은 문장 — 기한 대비 어떤지만 말한다"""
    st_ = g["status"]
    if st_ == "done":
        return "이미 목표 금액을 모았어요"
    if st_ == "unreachable":
        return "지금 속도로는 달성이 어려워요"
    gap = g.get("gap_months")
    if gap is None:
        return "기한이 없는 목표예요"
    if gap > 0:
        return f"기한보다 {months_text(gap)} 늦어요"
    if gap < 0:
        return f"기한보다 {months_text(gap)} 일찍 끝나요"
    return "기한에 맞춰 달성해요"


def friendly_summary(b: dict) -> str:
    """홈 상단 요약 — 숫자를 쉬운 말로 풀어 쓴다 (AI 문장이 없을 때 사용)"""
    parts = []
    budget = b["monthly_budget"]
    parts.append(f"매달 약 {short_won(budget)}이 남아요." if budget > 0
                 else f"매달 쓰는 돈이 수입보다 {short_won(-budget)} 많아요.")
    hp = b.get("headline_path")
    if hp:
        if hp["status"] == "unreachable":
            parts.append(f"지금 속도로는 '{hp['name']}'{josa(hp['name'], '을', '를')} 달성하기 어려워요.")
        elif hp["status"] != "done":
            parts.append(f"'{hp['name']}'{josa(hp['name'], '은', '는')} {ym(hp['completion_date'])}쯤 달성할 것 같아요 ({goal_gap_text(hp)}).")
    if b["actions"]:
        a = b["actions"][0]
        sentence, _ = effect_text(a["path_effect"], a["mandatory"])
        if a["mandatory"]:
            parts.append(f"먼저 '{a['title']}'부터 해 보세요.")
        else:
            parts.append(f"가장 효과가 큰 일은 '{a['title']}'이에요. {sentence}.")
    return " ".join(parts)
