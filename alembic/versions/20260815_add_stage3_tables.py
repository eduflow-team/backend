"""add stage3 debate tables

Revision ID: 20260815_stage3
Revises: 6031768b8c60
Create Date: 2026-08-15

Stage 3 과제 상세·토론 시도 테이블.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260815_stage3"
down_revision: Union[str, None] = "6031768b8c60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stage3_assignment_details",
        sa.Column("detail_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("assignment_id", sa.BigInteger(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("pro_persona", sa.String(length=100), nullable=False),
        sa.Column("con_persona", sa.String(length=100), nullable=False),
        sa.Column("fact_persona", sa.String(length=100), nullable=True),
        sa.Column("debate_mode", sa.String(length=10), server_default="v2", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["assignments.assignment_id"],
            name="fk_stage3_details_assignment",
        ),
        sa.PrimaryKeyConstraint("detail_id"),
        sa.UniqueConstraint("assignment_id", name="uq_stage3_details_assignment_id"),
    )
    op.create_table(
        "stage3_debate_attempts",
        sa.Column("attempt_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("assignment_id", sa.BigInteger(), nullable=False),
        sa.Column("submission_id", sa.BigInteger(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=True),
        sa.Column("debate_payload", sa.JSON(), nullable=True),
        sa.Column("checked_turn_ids", sa.JSON(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name="fk_stage3_attempts_user",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["assignments.assignment_id"],
            name="fk_stage3_attempts_assignment",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["submissions.submission_id"],
            name="fk_stage3_attempts_submission",
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
    )


def downgrade() -> None:
    op.drop_table("stage3_debate_attempts")
    op.drop_table("stage3_assignment_details")
