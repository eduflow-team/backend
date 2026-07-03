from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "eduflow"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = "postgresql+asyncpg://eduflow:eduflow@localhost:5432/eduflow"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
