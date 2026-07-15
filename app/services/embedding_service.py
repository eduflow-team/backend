"""문서 청킹·OpenAI 임베딩 유틸."""

from __future__ import annotations

import math
import re

import httpx

from app.core.config import settings
from app.core.exceptions import Stage1DocumentProcessingError, UnsupportedStage1FileTypeError


def split_text_into_chunks(text: str, chunk_size: int) -> list[str]:
    """문자 수 기준 단순 청킹. 문장 경계를 우선 고려한다."""

    normalized = re.sub(r"\r\n?", "\n", text).strip()
    if not normalized:
        return []

    if chunk_size < 50:
        chunk_size = 50

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", normalized) if p.strip()]
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for paragraph in paragraphs:
        if len(paragraph) <= chunk_size:
            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                flush()
                current = paragraph
            continue

        # 긴 문단은 공백 기준으로 잘라 chunk_size에 맞게 묶는다.
        flush()
        tokens = paragraph.split()
        buf = ""
        for token in tokens:
            candidate = f"{buf} {token}".strip() if buf else token
            if len(candidate) <= chunk_size:
                buf = candidate
                continue
            if buf:
                chunks.append(buf)
            if len(token) <= chunk_size:
                buf = token
            else:
                for i in range(0, len(token), chunk_size):
                    chunks.append(token[i : i + chunk_size])
                buf = ""
        if buf:
            chunks.append(buf)

    flush()
    return chunks


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """OpenAI embeddings API로 벡터를 생성한다. 차수는 config의 768에 맞춘다."""

    if not texts:
        return []
    if not settings.OPENAI_API_KEY:
        raise Stage1DocumentProcessingError(
            "OPENAI_API_KEY가 설정되지 않아 임베딩을 수행할 수 없습니다."
        )

    payload: dict = {
        "model": settings.OPENAI_EMBEDDING_MODEL,
        "input": texts,
    }
    if settings.OPENAI_EMBEDDING_DIMENSIONS:
        payload["dimensions"] = settings.OPENAI_EMBEDDING_DIMENSIONS

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise Stage1DocumentProcessingError(
            "문서 청크 분할 및 벡터 임베딩 처리 중 서버 오류가 발생했습니다."
        ) from exc

    items = sorted(data.get("data", []), key=lambda item: item.get("index", 0))
    embeddings = [item["embedding"] for item in items]
    if len(embeddings) != len(texts):
        raise Stage1DocumentProcessingError(
            "문서 청크 분할 및 벡터 임베딩 처리 중 서버 오류가 발생했습니다."
        )
    return embeddings


async def embed_text(text: str) -> list[float]:
    vectors = await embed_texts([text])
    return vectors[0]


def extract_text_from_upload(filename: str, content: bytes) -> str:
    """txt/md/pdf 업로드에서 본문 텍스트를 추출한다."""

    lower = filename.lower()
    if lower.endswith((".txt", ".md", ".markdown")):
        for encoding in ("utf-8", "cp949", "euc-kr"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="ignore")

    if lower.endswith(".pdf"):
        try:
            from io import BytesIO

            from pypdf import PdfReader
        except ImportError as exc:
            raise Stage1DocumentProcessingError(
                "PDF 처리를 위해 pypdf가 필요합니다."
            ) from exc

        reader = PdfReader(BytesIO(content))
        pages = [(page.extract_text() or "") for page in reader.pages]
        text = "\n\n".join(part.strip() for part in pages if part and part.strip())
        if not text.strip():
            raise Stage1DocumentProcessingError(
                "문서 청크 분할 및 벡터 임베딩 처리 중 서버 오류가 발생했습니다."
            )
        return text

    raise UnsupportedStage1FileTypeError()
