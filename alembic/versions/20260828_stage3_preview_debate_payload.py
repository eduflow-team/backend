"""add stage3 preview_debate_payload for teacher preview

Revision ID: 20260828_stage3_preview
Revises: 20260815_stage3
Create Date: 2026-08-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260828_stage3_preview"
down_revision: Union[str, None] = "20260815_stage3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stage3_assignment_details",
        sa.Column("preview_debate_payload", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stage3_assignment_details", "preview_debate_payload")
