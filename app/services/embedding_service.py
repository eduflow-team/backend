"""문서 청킹·OpenAI 임베딩 유틸."""

from __future__ import annotations

import asyncio
import logging
import math
import random
import re

import httpx

from app.core.config import settings
from app.core.exceptions import Stage1DocumentProcessingError, UnsupportedStage1FileTypeError

logger = logging.getLogger(__name__)

_EMBED_MAX_ATTEMPTS = 4
_EMBED_BACKOFF_BASE_SECONDS = 0.5
_EMBED_BODY_LOG_LIMIT = 500
_EMBED_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


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


def _truncate_body(text: str) -> str:
    cleaned = text.strip().replace("\n", " ")
    if len(cleaned) <= _EMBED_BODY_LOG_LIMIT:
        return cleaned
    return f"{cleaned[:_EMBED_BODY_LOG_LIMIT]}..."


def _retry_after_seconds(response: httpx.Response, attempt: int) -> float:
    """Retry-After가 있으면 우선, 없으면 exponential backoff(+jitter)."""

    header = response.headers.get("Retry-After")
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            pass
    return _EMBED_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 0.25)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """OpenAI embeddings API로 벡터를 생성한다. 차수는 config의 768에 맞춘다.

    429/5xx/timeout 등은 exponential backoff로 재시도하고,
    실패 시 HTTP status·body를 로그에 남긴다. 클라이언트 메시지는 공통 문구 유지.
    """

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

    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    last_exc: BaseException | None = None

    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(1, _EMBED_MAX_ATTEMPTS + 1):
            try:
                response = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers=headers,
                    json=payload,
                )
                if response.is_success:
                    data = response.json()
                    break

                body = _truncate_body(response.text)
                retryable = response.status_code in _EMBED_RETRYABLE_STATUS
                if retryable and attempt < _EMBED_MAX_ATTEMPTS:
                    delay = _retry_after_seconds(response, attempt)
                    logger.warning(
                        "OpenAI embeddings 일시 오류 (attempt=%s/%s, status=%s, "
                        "retry_in=%.2fs, body=%s)",
                        attempt,
                        _EMBED_MAX_ATTEMPTS,
                        response.status_code,
                        delay,
                        body,
                    )
                    await asyncio.sleep(delay)
                    continue

                logger.error(
                    "OpenAI embeddings 실패 (attempt=%s/%s, status=%s, body=%s)",
                    attempt,
                    _EMBED_MAX_ATTEMPTS,
                    response.status_code,
                    body,
                )
                raise Stage1DocumentProcessingError(
                    "문서 청크 분할 및 벡터 임베딩 처리 중 서버 오류가 발생했습니다."
                )
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < _EMBED_MAX_ATTEMPTS:
                    delay = _EMBED_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        "OpenAI embeddings timeout (attempt=%s/%s, retry_in=%.2fs, error=%s)",
                        attempt,
                        _EMBED_MAX_ATTEMPTS,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(
                    "OpenAI embeddings timeout 최종 실패 (attempts=%s, error=%s)",
                    _EMBED_MAX_ATTEMPTS,
                    exc,
                )
                raise Stage1DocumentProcessingError(
                    "문서 청크 분할 및 벡터 임베딩 처리 중 서버 오류가 발생했습니다."
                ) from exc
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < _EMBED_MAX_ATTEMPTS:
                    delay = _EMBED_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        "OpenAI embeddings 연결 오류 (attempt=%s/%s, retry_in=%.2fs, "
                        "error=%s)",
                        attempt,
                        _EMBED_MAX_ATTEMPTS,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(
                    "OpenAI embeddings 연결 오류 최종 실패 (attempts=%s, error=%s)",
                    _EMBED_MAX_ATTEMPTS,
                    exc,
                )
                raise Stage1DocumentProcessingError(
                    "문서 청크 분할 및 벡터 임베딩 처리 중 서버 오류가 발생했습니다."
                ) from exc
        else:
            raise Stage1DocumentProcessingError(
                "문서 청크 분할 및 벡터 임베딩 처리 중 서버 오류가 발생했습니다."
            ) from last_exc

    items = sorted(data.get("data", []), key=lambda item: item.get("index", 0))
    embeddings = [item["embedding"] for item in items]
    if len(embeddings) != len(texts):
        logger.error(
            "OpenAI embeddings 응답 개수 불일치 (expected=%s, got=%s)",
            len(texts),
            len(embeddings),
        )
        raise Stage1DocumentProcessingError(
            "문서 청크 분할 및 벡터 임베딩 처리 중 서버 오류가 발생했습니다."
        )
    return embeddings


async def embed_text(text: str) -> list[float]:
    vectors = await embed_texts([text])
    return vectors[0]


def _hangul_count(text: str) -> int:
    return len(re.findall(r"[가-힣]", text or ""))


def _pdf_text_insufficient(text: str, *, page_count: int) -> bool:
    """이미지 PDF처럼 본문이 거의 없는 추출 결과를 판별한다."""

    stripped = (text or "").strip()
    if not stripped:
        return True
    min_chars = max(int(settings.STAGE1_PDF_OCR_MIN_CHARS), page_count * 40)
    min_hangul = max(int(settings.STAGE1_PDF_OCR_MIN_HANGUL), page_count * 15)
    if len(stripped) < min_chars:
        return True
    if _hangul_count(stripped) < min_hangul:
        return True
    return False


def _extract_pdf_text_layer(content: bytes) -> tuple[str, int]:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    pages = [(page.extract_text() or "") for page in reader.pages]
    text = "\n\n".join(part.strip() for part in pages if part and part.strip())
    return text, len(reader.pages)


def _render_pdf_pages_png(content: bytes, *, dpi: int, max_pages: int) -> list[bytes]:
    import fitz  # pymupdf

    doc = fitz.open(stream=content, filetype="pdf")
    try:
        images: list[bytes] = []
        zoom = max(dpi, 72) / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        limit = min(len(doc), max_pages)
        for index in range(limit):
            page = doc.load_page(index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            images.append(pix.tobytes("png"))
        return images
    finally:
        doc.close()


def _ocr_png_with_tesseract(png_bytes: bytes, *, lang: str) -> str:
    from io import BytesIO

    import pytesseract
    from PIL import Image

    image = Image.open(BytesIO(png_bytes))
    return (pytesseract.image_to_string(image, lang=lang) or "").strip()


def _ocr_pdf_with_tesseract(content: bytes) -> str | None:
    """시스템 Tesseract가 있으면 페이지 렌더 + OCR. 없으면 None."""

    try:
        import pytesseract
    except ImportError:
        return None

    try:
        pytesseract.get_tesseract_version()
    except Exception:  # noqa: BLE001
        logger.info("tesseract binary not available; skip local OCR")
        return None

    lang = settings.STAGE1_PDF_OCR_LANG
    dpi = int(settings.STAGE1_PDF_OCR_DPI)
    max_pages = int(settings.STAGE1_PDF_OCR_MAX_PAGES)
    try:
        images = _render_pdf_pages_png(content, dpi=dpi, max_pages=max_pages)
    except Exception:  # noqa: BLE001
        logger.exception("pdf render for tesseract OCR failed")
        return None

    parts: list[str] = []
    for png in images:
        try:
            text = _ocr_png_with_tesseract(png, lang=lang)
        except Exception:  # noqa: BLE001
            logger.exception("tesseract OCR page failed")
            continue
        if text:
            parts.append(text)
    joined = "\n\n".join(parts).strip()
    return joined or None


def _ocr_png_with_openai(png_bytes: bytes, *, page_no: int) -> str:
    if not settings.OPENAI_API_KEY:
        return ""

    import base64

    b64 = base64.b64encode(png_bytes).decode("ascii")
    prompt = (
        "이 이미지는 학습 교재 PDF 페이지입니다. "
        "페이지에 보이는 본문 텍스트만 한국어/영어 그대로 추출하세요. "
        "설명·번역·요약 금지. 읽기 어려운 부분은 건너뛰세요."
    )
    try:
        with httpx.Client(timeout=90.0) as client:
            response = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.OPENAI_CHAT_MODEL,
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": f"[page {page_no}]\n{prompt}"},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{b64}",
                                        "detail": "high",
                                    },
                                },
                            ],
                        }
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()
        return (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
    except Exception:  # noqa: BLE001
        logger.exception("openai vision OCR failed page=%s", page_no)
        return ""


def _ocr_pdf_with_openai(content: bytes) -> str | None:
    if not settings.STAGE1_PDF_OCR_OPENAI_FALLBACK or not settings.OPENAI_API_KEY:
        return None

    dpi = int(settings.STAGE1_PDF_OCR_DPI)
    max_pages = int(settings.STAGE1_PDF_OCR_MAX_PAGES)
    try:
        images = _render_pdf_pages_png(content, dpi=dpi, max_pages=max_pages)
    except Exception:  # noqa: BLE001
        logger.exception("pdf render for openai OCR failed")
        return None

    parts: list[str] = []
    for index, png in enumerate(images, start=1):
        text = _ocr_png_with_openai(png, page_no=index)
        if text:
            parts.append(text)
    joined = "\n\n".join(parts).strip()
    return joined or None


def extract_text_from_upload(filename: str, content: bytes) -> str:
    """txt/md/pdf 업로드에서 본문 텍스트를 추출한다.

    PDF는 먼저 텍스트 레이어(pypdf)를 읽고, 본문이 빈약하면 OCR 폴백한다.
    OCR 우선순위: Tesseract(로컬/Docker) → OpenAI Vision.
    """

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
            text, page_count = _extract_pdf_text_layer(content)
        except ImportError as exc:
            raise Stage1DocumentProcessingError(
                "PDF 처리를 위해 pypdf가 필요합니다."
            ) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("pdf text-layer extraction failed")
            raise Stage1DocumentProcessingError() from exc

        needs_ocr = settings.STAGE1_PDF_OCR_ENABLED and _pdf_text_insufficient(
            text, page_count=page_count
        )
        if not needs_ocr and text.strip():
            return text

        logger.info(
            "pdf OCR fallback start file=%s pages=%s text_len=%s hangul=%s",
            filename,
            page_count,
            len(text or ""),
            _hangul_count(text or ""),
        )

        ocr_text = _ocr_pdf_with_tesseract(content)
        if ocr_text and not _pdf_text_insufficient(ocr_text, page_count=page_count):
            logger.info("pdf OCR via tesseract ok chars=%s", len(ocr_text))
            return ocr_text

        ocr_text = _ocr_pdf_with_openai(content)
        if ocr_text and ocr_text.strip():
            logger.info("pdf OCR via openai ok chars=%s", len(ocr_text))
            return ocr_text

        if text.strip():
            # OCR 실패해도 텍스트 레이어라도 있으면 사용 (최후)
            logger.warning("pdf OCR failed; using weak text-layer extract")
            return text

        raise Stage1DocumentProcessingError(
            "이미지 PDF에서 텍스트를 추출하지 못했습니다. "
            "OCR(Tesseract 한글) 설치 또는 OpenAI API 키를 확인해 주세요."
        )

    raise UnsupportedStage1FileTypeError()
