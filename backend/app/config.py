"""애플리케이션 환경 설정"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM
    openai_api_key: str = ""
    llm_base_url: str = ""          # vLLM 등 OpenAI 호환 서버 주소 (예: http://host:8000/v1). 비우면 OpenAI API
    llm_model: str = "gpt-4o-mini"  # vLLM은 서빙 중인 모델 경로/이름
    llm_timeout: float = 30.0

    # Database
    database_url: str = "sqlite:///./afpa.db"

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    # 외부 금융 API
    fss_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
