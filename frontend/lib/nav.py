"""화면 이동 도우미 — app.py가 st.navigation 으로 만든 페이지를 세션에 보관한다"""
import streamlit as st


def register(pages: dict) -> None:
    st.session_state["_pages"] = pages


def go(key: str) -> None:
    pages = st.session_state.get("_pages", {})
    if key in pages:
        st.switch_page(pages[key])
