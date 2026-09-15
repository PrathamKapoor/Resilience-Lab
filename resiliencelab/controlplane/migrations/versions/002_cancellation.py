"""add cancellation fields

Revision ID: 002
Revises: 001
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: str = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "experiments",
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "experiments",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("runs", "cancelled_at")
    op.drop_column("runs", "cancellation_reason")
    op.drop_column("experiments", "cancelled_at")
    op.drop_column("experiments", "cancellation_reason")
