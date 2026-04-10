from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    whatsapp_api_base_url: str = "https://sistema-whatsapp-api.5mos1l.easypanel.host"
    whatsapp_instance_token: str = ""
    public_base_url: str = "http://localhost:8000"
    redis_url: str = "redis://default:85885885@31.97.252.6:1013"
    request_timeout_seconds: int = 30
    openai_api_key: str = ""
    admin_user: str = "admin"
    admin_password: str = "admin123"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
