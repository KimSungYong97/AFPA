"""백엔드 API 호출 + 사용자 상태 (화면 코드가 공통으로 사용)"""
import os
from typing import Any, Optional, Tuple

import httpx
import streamlit as st

DEFAULT_API = os.getenv("AFPA_API_URL", "http://127.0.0.1:8080")


def base_url() -> str:
    url = st.session_state.get("api_url", DEFAULT_API).rstrip("/")
    # Windows에서 localhost 는 IPv6 시도 때문에 호출마다 2초 이상 지연되므로 127.0.0.1 로 바꾼다
    return url.replace("://localhost", "://127.0.0.1")


def call(method: str, path: str, **kwargs) -> Tuple[Optional[int], Any]:
    """(상태코드, JSON). 연결 실패 시 (None, 안내 문구)"""
    try:
        r = httpx.request(method, base_url() + path, timeout=60, **kwargs)
    except httpx.HTTPError as e:
        return None, f"서버에 연결할 수 없어요. ({e})"
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def error_text(body: Any) -> str:
    if isinstance(body, dict) and "detail" in body:
        d = body["detail"]
        return d if isinstance(d, str) else str(d)
    return str(body)


def ctx() -> dict:
    """현재 선택된 사용자와 화면 설정 (app.py가 채운다)"""
    return st.session_state["ctx"]


def uid() -> int:
    return ctx()["user"]["id"]


def get_ok(path: str, **params) -> Tuple[bool, Any]:
    status, body = call("GET", path, params=params or None)
    return status == 200, body


def post_ok(path: str, json: Optional[dict] = None, **params) -> Tuple[bool, Any]:
    status, body = call("POST", path, json=json, params=params or None)
    return status in (200, 201), body
