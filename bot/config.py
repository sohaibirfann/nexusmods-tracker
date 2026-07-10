import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    discord_bot_token: str
    backend_url: str = "http://localhost:8000"
    internal_api_key: str
    poll_interval_minutes: int = 60


settings = Settings()

# one client for the process; X-API-Key rides on every request as a default header
api = httpx.AsyncClient(
    base_url=settings.backend_url,
    headers={"X-API-Key": settings.internal_api_key},
    timeout=30,
)
