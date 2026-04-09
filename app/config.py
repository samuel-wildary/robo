from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    whatsapp_api_base_url: str = "https://sistema-whatsapp-api.5mos1l.easypanel.host"
    whatsapp_instance_token: str = ""
    public_base_url: str = "http://localhost:8000"
    flow_file: Path = Path("flows/flows.json")
    database_url: str = ""
    redis_url: str = "redis://default:85885885@31.97.252.6:1013"
    request_timeout_seconds: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
