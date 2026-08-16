"""기존 Stage2 과제의 documents.raw_text를 최신 발췌 로직으로 재생성한다.

사용:
  python scripts/refresh_stage2_reference_text.py
  python scripts/refresh_stage2_reference_text.py --assignment-id 111

업로드 PDF/TXT 원본(file_path)이 있으면 그걸 다시 파싱하고,
없으면 기존 raw_text를 source로 사용한다.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import AsyncSessionLocal
from app.repositories.document import DocumentRepository
from app.repositories.stage import Stage2DetailRepository
from app.services.embedding_service import extract_text_from_upload
from app.services.stage2_document_context import resolve_stage2_document_context

# excerpt PDF에 본문 단원이 없을 때 학생 UI용 최소 발췌 (과제별)
CURATED_REFERENCE_TEXT: dict[int, str] = {
    111: (
        "06 교역망의 발달과 은 유통 ~ 사회 변동과 서민 문화\n\n"
        "17세기 전후 동아시아에서는 교역망이 확대되며 은이 유통되었다. "
        "명과 청은 해상 교역을 통해 주변 국가와 교류하였다. "
        "교역은 상업 발달과 사회 변동에 영향을 주었으나, "
        "정치·경제적 통제와 제한 속에서 운영되기도 하였다."
    ),
}


async def refresh_assignment(assignment_id: int) -> None:
    async with AsyncSessionLocal() as session:
        detail_repo = Stage2DetailRepository(session)
        document_repo = DocumentRepository(session)

        detail = await detail_repo.get_by_assignment_id(assignment_id)
        if detail is None:
            raise SystemExit(f"stage2 detail not found for assignment_id={assignment_id}")

        document = await document_repo.get_by_id(detail.document_id)
        if document is None:
            raise SystemExit(f"document_id={detail.document_id} not found")

        question = (detail.question or "").strip()
        if not question:
            raise SystemExit("assignment question is empty")

        source_text = (document.raw_text or "").strip()
        file_path = document.file_path
        if file_path:
            path = Path(file_path)
            if not path.is_absolute():
                path = ROOT / path
            if path.exists():
                source_text = extract_text_from_upload(
                    document.filename or path.name,
                    path.read_bytes(),
                ).strip()

        if not source_text:
            raise SystemExit("no source text available to rebuild excerpt")

        if assignment_id in CURATED_REFERENCE_TEXT:
            new_text = CURATED_REFERENCE_TEXT[assignment_id].strip()
            was_trimmed = False
        else:
            context = resolve_stage2_document_context(
                source_text=source_text,
                question=question,
            )
            new_text = context.generation_text.strip()
            was_trimmed = context.was_trimmed
            if not new_text:
                raise SystemExit("resolved excerpt is empty")

        old_len = len((document.raw_text or "").strip())
        await document_repo.update_raw_text(document, new_text)
        await session.commit()

        print(f"assignment_id={assignment_id} document_id={document.document_id}")
        print(f"raw_text updated: {old_len} -> {len(new_text)} chars")
        print(f"was_trimmed={was_trimmed}")
        print(f"preview: {new_text[:200]}...")


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh stage2 reference excerpt in DB")
    parser.add_argument(
        "--assignment-id",
        type=int,
        default=111,
        help="Stage2 assignment ID (default: 111)",
    )
    args = parser.parse_args()
    asyncio.run(refresh_assignment(args.assignment_id))


if __name__ == "__main__":
    main()
