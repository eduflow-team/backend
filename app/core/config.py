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
    LANGFLOW_STAGE3_FLOW_ID: str = ""
    LANGFLOW_STAGE3_V2_FLOW_ID: str = ""
    LANGFLOW_STAGE3_PRO_AGENT_ID: str = "LM-s3pro"
    LANGFLOW_STAGE3_CON_AGENT_ID: str = "LM-s3con"
    LANGFLOW_STAGE3_FACT_AGENT_ID: str = "LM-s3fact"
    LANGFLOW_STAGE3_V1_ENDPOINT: str = "stage3-debate"
    LANGFLOW_STAGE3_V2_ENDPOINT: str = "stage3-debate-v2"

    # Stage 4 (프롬프트 인젝션)
    LANGFLOW_STAGE4_CHAT_FLOW_ID: str = ""
    LANGFLOW_STAGE4_PROMPT_NODE_ID: str = ""

    # Stage 1 업로드 제한
    STAGE1_MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024  # 10MB
    # 답안 제출 최대 횟수 (채팅은 제한 없음)
    STAGE1_MAX_ATTEMPTS: int = 2
    # chat/create에서 허용하는 chunk_size (업로드 시 preset 전부 임베딩)
    STAGE1_CHUNK_SIZE_PRESETS: tuple[int, ...] = (50, 200, 500, 1200, 3000)
    # 교사 출제 시 학생 시작 파라미터 (교사 UI에서 설정하지 않음 · 고정)
    STAGE1_DEFAULT_CHUNK_SIZE: int = 50
    STAGE1_DEFAULT_TOP_K: int = 2
    STAGE1_DEFAULT_TEMPERATURE: float = 1.0
    # 최종 = 정답점수(0|100) − w×resource_penalty(0~100). temperature 감점 없음.
    STAGE1_RESOURCE_PENALTY_WEIGHT: float = 0.3  # 최대 약 30점 감점
    STAGE1_K_SCALE: int = 6  # default top_k 대비 +6이면 top_k 축 만땅
    STAGE1_CHUNK_SCALE: int = 3  # preset 3단계 올리면 chunk 축 만땅
    STAGE1_RESOURCE_TOP_K_WEIGHT: float = 0.6
    STAGE1_RESOURCE_CHUNK_WEIGHT: float = 0.4
    # 학생 detail에 내려줄 추출 텍스트 상한(문자)
    STAGE1_DOCUMENT_TEXT_MAX_CHARS: int = 80_000
    # 이미지 PDF OCR: pypdf 텍스트가 빈약하면 활성화
    STAGE1_PDF_OCR_ENABLED: bool = True
    STAGE1_PDF_OCR_MIN_CHARS: int = 200
    STAGE1_PDF_OCR_MIN_HANGUL: int = 80
    STAGE1_PDF_OCR_DPI: int = 200
    STAGE1_PDF_OCR_LANG: str = "kor+eng"
    # Tesseract 없을 때 OpenAI Vision으로 페이지 OCR (비용 발생)
    STAGE1_PDF_OCR_OPENAI_FALLBACK: bool = True
    STAGE1_PDF_OCR_MAX_PAGES: int = 40
    # 검색 약할 때 Langflow context에 WEAK 모드(+노이즈) 주입 (UI preview에는 미포함)
    STAGE1_WEAK_MAX_CHARS: int = 350
    STAGE1_WEAK_MAX_SCORE: float = 0.42
    STAGE1_WEAK_CHUNK_SIZE: int = 50
    STAGE1_WEAK_TOP_K: int = 2
    STAGE1_WEAK_NOISE_ENABLED: bool = True

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

    # Stage 3
    STAGE3_MAX_ATTEMPTS: int = 3
    # Langflow 미연결 로컬 개발 시에만 true (기본: 503)
    STAGE3_ALLOW_MOCK: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
