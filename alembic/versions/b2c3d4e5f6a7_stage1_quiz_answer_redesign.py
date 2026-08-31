"""stage1 quiz answer redesign: purge old stage1, add answer, drop optimal

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-18 13:50:00.000000

기존 Stage1 시나리오(AI 답 선택·optimal 채점) 데이터를 삭제하고
교사 출제 퀴즈(정답 1개) 스키마로 전환한다. 호환 없음 — 과제 재출제 필요.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Stage1 관련 행 전부 삭제 (FK 순서)
    conn.execute(
        sa.text(
            """
            DELETE FROM evaluations
            WHERE submission_id IN (
                SELECT s.submission_id FROM submissions s
                JOIN assignments a ON a.assignment_id = s.assignment_id
                WHERE a.stage = 1
            )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM stage1_attempts
            WHERE assignment_id IN (
                SELECT assignment_id FROM assignments WHERE stage = 1
            )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM submissions
            WHERE assignment_id IN (
                SELECT assignment_id FROM assignments WHERE stage = 1
            )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM student_assignment_status
            WHERE assignment_id IN (
                SELECT assignment_id FROM assignments WHERE stage = 1
            )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM document_chunks
            WHERE document_id IN (
                SELECT d.document_id FROM documents d
                JOIN assignments a ON a.assignment_id = d.assignment_id
                WHERE a.stage = 1
            )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM documents
            WHERE assignment_id IN (
                SELECT assignment_id FROM assignments WHERE stage = 1
            )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM stage1_assignment_details
            WHERE assignment_id IN (
                SELECT assignment_id FROM assignments WHERE stage = 1
            )
            """
        )
    )
    conn.execute(sa.text("DELETE FROM assignments WHERE stage = 1"))

    op.add_column(
        "stage1_assignment_details",
        sa.Column("answer", sa.Text(), nullable=True),
    )
    op.drop_column("stage1_assignment_details", "optimal_parameters")
    # Stage1에 쓰이지 않던 Stage2 잔여 컬럼 정리
    op.drop_column("stage1_assignment_details", "persona")
    op.drop_column("stage1_assignment_details", "hallucination_types")
    op.drop_column("stage1_assignment_details", "hallucination_hint")
    op.drop_column("stage1_assignment_details", "expected_hallucination_count")


def downgrade() -> None:
    op.add_column(
        "stage1_assignment_details",
        sa.Column("expected_hallucination_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "stage1_assignment_details",
        sa.Column("hallucination_hint", sa.Text(), nullable=True),
    )
    op.add_column(
        "stage1_assignment_details",
        sa.Column("hallucination_types", sa.JSON(), nullable=True),
    )
    op.add_column(
        "stage1_assignment_details",
        sa.Column("persona", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "stage1_assignment_details",
        sa.Column("optimal_parameters", sa.JSON(), nullable=True),
    )
    op.drop_column("stage1_assignment_details", "answer")
