from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    nexus_api_key: str
    database_url: str
    internal_api_key: str


settings = Settings()
