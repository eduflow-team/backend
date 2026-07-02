from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.repositories.base import BaseRepository


class DocumentRepository(BaseRepository[Document]):
    model = Document

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_assignment_id(self, assignment_id: int) -> list[Document]:
        stmt = (
            select(Document)
            .where(Document.assignment_id == assignment_id)
            .order_by(Document.document_id)
        )
        stmt = self._apply_not_deleted(stmt)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_raw_text(self, document: Document, raw_text: str) -> Document:
        document.raw_text = raw_text
        return await self.update(document)
