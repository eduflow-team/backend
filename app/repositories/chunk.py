from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentChunk
from app.repositories.base import BaseRepository


class DocumentChunkRepository(BaseRepository[DocumentChunk]):
    model = DocumentChunk

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def bulk_create(self, chunks: list[DocumentChunk]) -> list[DocumentChunk]:
        self.session.add_all(chunks)
        await self.session.flush()
        for chunk in chunks:
            await self.session.refresh(chunk)
        return chunks

    async def get_by_document_id(self, document_id: int) -> list[DocumentChunk]:
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_document_id(self, document_id: int) -> None:
        stmt = delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        await self.session.execute(stmt)
        await self.session.flush()

    async def search_similar(
        self,
        embedding: list[float],
        *,
        document_id: int | None = None,
        top_k: int = 5,
    ) -> list[DocumentChunk]:
        distance = DocumentChunk.embedding.cosine_distance(embedding)
        stmt = select(DocumentChunk).where(DocumentChunk.embedding.is_not(None))
        if document_id is not None:
            stmt = stmt.where(DocumentChunk.document_id == document_id)
        stmt = stmt.order_by(distance).limit(top_k)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
