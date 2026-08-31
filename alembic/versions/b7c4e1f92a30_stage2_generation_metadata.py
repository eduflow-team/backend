"""stage2 generation metadata column

Revision ID: b7c4e1f92a30
Revises: 6031768b8c60
Create Date: 2026-07-27 16:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c4e1f92a30"
down_revision: Union[str, None] = "6031768b8c60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stage2_assignment_details",
        sa.Column("generation_metadata", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stage2_assignment_details", "generation_metadata")
