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

    # OpenAI (문서 임베딩·질의 임베딩·채점 피드백용)
    OPENAI_API_KEY: str = ""
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_EMBEDDING_DIMENSIONS: int = 768
    OPENAI_CHAT_MODEL: str = "gpt-4o-mini"

    # Langflow
    LANGFLOW_URL: str = "http://localhost:7860"
    LANGFLOW_API_KEY: str = ""
    LANGFLOW_STAGE1_CHAT_FLOW_ID: str = ""
    LANGFLOW_STAGE1_PROMPT_NODE_ID: str = ""
    LANGFLOW_STAGE1_MODEL_NODE_ID: str = ""
    LANGFLOW_STAGE2_FLOW_ID: str = ""
    LANGFLOW_STAGE2_GEN_PROMPT_NODE_ID: str = ""
    LANGFLOW_STAGE2_EXT_PROMPT_NODE_ID: str = ""

    # Stage 1 업로드 제한
    STAGE1_MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024  # 10MB
    STAGE1_MAX_ATTEMPTS: int = 3
    # chat/create에서 허용하는 chunk_size (업로드 시 전부에 전부 임베딩)
    STAGE1_CHUNK_SIZE_PRESETS: tuple[int, ...] = (50, 200, 500, 1200, 3000)

    # Stage 2
    STAGE2_MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024  # 10MB
    STAGE2_MAX_ATTEMPTS: int = 5
    STAGE2_LOCATION_THRESHOLD: float = 0.8
    STAGE2_REASONING_THRESHOLD: float = 0.95
    STAGE2_CORRECTION_MIN_SCORE: int = 4

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
