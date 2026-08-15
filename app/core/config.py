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

    # OpenAI (문서 임베딩·질의 임베딩·Stage2 G-Eval 채점)
    OPENAI_API_KEY: str = ""
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_EMBEDDING_DIMENSIONS: int = 768
    OPENAI_CHAT_MODEL: str = "gpt-4o-mini"

    # Langflow (Stage1: 미설정 시 503 / Stage2: 미설정 시 mock)
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
    # 최종점수 = 0.8×optimal근접 + 0.2×답변품질
    STAGE1_PROXIMITY_WEIGHT: float = 0.8
    STAGE1_QUALITY_WEIGHT: float = 0.2
    # optimal 탐색: 최고 품질의 이 비율 이상인 후보 중 가장 약한 설정을 고름
    STAGE1_OPTIMAL_ELBOW_RATIO: float = 0.90
    STAGE1_OPTIMAL_TOP_K_CANDIDATES: tuple[int, ...] = (1, 2, 3, 5, 8)
    STAGE1_OPTIMAL_TEMP_CANDIDATES: tuple[float, ...] = (0.0, 0.2, 0.5, 1.0)
    STAGE1_OPTIMAL_FALLBACK: dict = {
        "chunk_size": 500,
        "top_k": 3,
        "temperature": 0.2,
    }
    # 학생 AI 채팅·optimal 탐색용 고정 질문
    STAGE1_FIXED_CHAT_MESSAGE: str = "오늘 학습 주제의 내용을 전체적으로 알려줘"
    # 학생 AI 채팅용 고정 질문 가이드 (교사가 입력하지 않음)
    STAGE1_FIXED_GUIDELINE: str = (
        '"오늘 학습 주제의 내용을 전체적으로 알려줘"라고 AI에게 질문해보세요.'
    )
    STAGE1_QUESTION_FALLBACK: str = (
        "업로드한 학습 자료에 대해 AI에게 질문하고, "
        "파라미터를 조절하여 자료에 가장 잘 맞는 답변을 찾아보세요."
    )
    # 이미지 PDF OCR: pypdf 텍스트가 빈약하면 활성화
    STAGE1_PDF_OCR_ENABLED: bool = True
    STAGE1_PDF_OCR_MIN_CHARS: int = 200
    STAGE1_PDF_OCR_MIN_HANGUL: int = 80
    STAGE1_PDF_OCR_DPI: int = 200
    STAGE1_PDF_OCR_LANG: str = "kor+eng"
    # Tesseract 없을 때 OpenAI Vision으로 페이지 OCR (비용 발생)
    STAGE1_PDF_OCR_OPENAI_FALLBACK: bool = True
    STAGE1_PDF_OCR_MAX_PAGES: int = 40

    # Stage 2
    STAGE2_MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024  # 10MB
    STAGE2_MAX_ATTEMPTS: int = 5
    STAGE2_GENERATION_MAX_ATTEMPTS: int = 3
    STAGE2_FLOW_VERSION: str = "stage2-v2"
    STAGE2_LOCATION_THRESHOLD: float = 0.8
    STAGE2_REASONING_THRESHOLD: float = 0.95
    STAGE2_CORRECTION_MIN_SCORE: int = 4
    STAGE2_CHUNK_SIZE: int = 400
    STAGE2_MIN_CHUNK_CHARS: int = 30
    STAGE2_MAX_CHUNK_CANDIDATES: int = 5
    STAGE2_MAX_CANDIDATE_TOTAL_CHARS: int = 4000
    STAGE2_GENERATION_DOCUMENT_MAX_CHARS: int = 6000
    STAGE2_STUDENT_EXCERPT_MAX_CHARS: int = 1200

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
