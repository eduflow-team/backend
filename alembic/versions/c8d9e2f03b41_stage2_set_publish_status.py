"""stage2 set_id and publish_status on assignments

Revision ID: c8d9e2f03b41
Revises: b7c4e1f92a30
Create Date: 2026-07-27 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d9e2f03b41"
down_revision: Union[str, None] = "b7c4e1f92a30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assignments",
        sa.Column("set_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "assignments",
        sa.Column(
            "publish_status",
            sa.String(length=20),
            nullable=False,
            server_default="PUBLISHED",
        ),
    )


def downgrade() -> None:
    op.drop_column("assignments", "publish_status")
    op.drop_column("assignments", "set_id")
