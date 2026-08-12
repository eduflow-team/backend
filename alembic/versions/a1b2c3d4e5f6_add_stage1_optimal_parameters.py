"""add stage1 optimal_parameters

Revision ID: a1b2c3d4e5f6
Revises: 6031768b8c60
Create Date: 2026-08-12 13:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "6031768b8c60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stage1_assignment_details",
        sa.Column("optimal_parameters", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stage1_assignment_details", "optimal_parameters")
