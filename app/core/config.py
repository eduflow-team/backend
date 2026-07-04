from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "eduflow"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = "postgresql+asyncpg://eduflow:eduflow@localhost:5432/eduflow"

    # 교사 회원가입 시 요구되는 인증 코드(임시 코드)
    TEACHER_SIGNUP_CODE: str = "TEACHER_SECRET_CODE"

    # JWT
    JWT_SECRET_KEY: str = "dev-secret-key-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 10080

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
