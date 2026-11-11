"""가맹점명 정규화 (캐시 키·사전 조회 키)"""
import re

_PAREN = re.compile(r"[\(\[（].*?[\)\]）]")
_CORP = re.compile(r"(주식회사|\(주\)|㈜)")
_SPACES = re.compile(r"\s+")
_BRANCH_TOKEN = re.compile(r"^(.{1,10}?)(지점|점)$")


def normalize_merchant(name: str) -> str:
    """지점명·괄호·법인 표기를 제거한 비교용 상호명.

    예) "스타벅스 역삼점" → "스타벅스", "(주)케이엔제이" → "케이엔제이"
    마지막 토큰이 지점 표기("…점", "…지점")이고 앞에 상호가 남을 때만 제거한다.
    """
    if not name:
        return ""
    s = _CORP.sub("", name)
    s = _PAREN.sub("", s)
    s = _SPACES.sub(" ", s).strip()
    tokens = s.split(" ")
    if len(tokens) >= 2 and _BRANCH_TOKEN.match(tokens[-1]):
        tokens = tokens[:-1]
    return " ".join(tokens).casefold()
