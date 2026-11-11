"""공통 화면 요소 (카드·배지·큰 숫자) — 라이트/다크 테마 모두에서 읽히도록 투명 배경과 상속 색을 쓴다"""
import html
from typing import Optional

import streamlit as st

TONES = {                      # (글자색, 배경색)
    "good": ("#1a7f4b", "rgba(46,160,100,0.14)"),
    "warn": ("#b26a00", "rgba(245,166,35,0.18)"),
    "bad": ("#c0392b", "rgba(231,76,60,0.15)"),
    "info": ("#2563b8", "rgba(52,120,220,0.14)"),
    "gray": ("#6b7280", "rgba(128,128,128,0.14)"),
}

_CSS = """
<style>
.block-container {padding-top: 2rem; max-width: 1100px;}
.afpa-card {border: 1px solid rgba(128,128,128,0.25); border-radius: 16px; padding: 18px 20px;
            background: rgba(128,128,128,0.05); min-height: 150px;}
.afpa-hero {border-radius: 18px; padding: 20px 24px; background: rgba(52,120,220,0.10);
            border: 1px solid rgba(52,120,220,0.25); font-size: 1.08rem; line-height: 1.7;}
.afpa-label {font-size: 0.85rem; opacity: 0.7; margin-bottom: 4px;}
.afpa-big {font-size: 1.9rem; font-weight: 700; line-height: 1.25;}
.afpa-sub {font-size: 0.88rem; opacity: 0.75; margin-top: 6px; line-height: 1.5;}
.afpa-badge {display: inline-block; padding: 3px 11px; border-radius: 999px; font-size: 0.82rem;
             font-weight: 600; margin-right: 6px;}
.afpa-num {display: inline-block; width: 28px; height: 28px; border-radius: 50%; text-align: center;
           line-height: 28px; font-weight: 700; margin-right: 8px; background: rgba(52,120,220,0.18);}
.afpa-title {font-size: 1.08rem; font-weight: 650;}
.afpa-muted {opacity: 0.7; font-size: 0.9rem;}
.afpa-step {border-radius: 12px; padding: 10px 14px; border: 1px solid rgba(128,128,128,0.25); margin-bottom: 8px;}
div[data-testid="stMetric"] {background: rgba(128,128,128,0.05); border-radius: 14px; padding: 10px 14px;}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def esc(text) -> str:
    return html.escape(str(text))


def badge(text: str, tone: str = "gray") -> str:
    fg, bg = TONES.get(tone, TONES["gray"])
    return f'<span class="afpa-badge" style="color:{fg};background:{bg}">{esc(text)}</span>'


def card(inner_html: str) -> None:
    st.markdown(f'<div class="afpa-card">{inner_html}</div>', unsafe_allow_html=True)


def hero(text: str) -> None:
    st.markdown(f'<div class="afpa-hero">{esc(text)}</div>', unsafe_allow_html=True)


def stat(label: str, value: str, sub: str = "", tone: Optional[str] = None, badge_text: str = "") -> None:
    """큰 숫자 카드"""
    color = f' style="color:{TONES[tone][0]}"' if tone in TONES else ""
    b = badge(badge_text, tone or "gray") if badge_text else ""
    st.markdown(
        f'<div class="afpa-card"><div class="afpa-label">{esc(label)}</div>'
        f'<div class="afpa-big"{color}>{esc(value)}</div>'
        f'<div class="afpa-sub">{b}{esc(sub)}</div></div>', unsafe_allow_html=True)


def section(title: str, caption: str = "") -> None:
    st.markdown(f"### {title}")
    if caption:
        st.caption(caption)


def empty_state(message: str, button_label: str = "", target: str = "") -> None:
    """데이터가 없을 때 다음 행동을 안내한다"""
    with st.container(border=True):
        st.markdown(f"**{message}**")
        if button_label and target:
            from lib.nav import go
            if st.button(button_label, type="primary", key=f"empty_{target}"):
                go(target)
