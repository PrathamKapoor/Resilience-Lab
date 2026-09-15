"""add owner_id for authorization

Revision ID: 003
Revises: 002
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "experiments",
        sa.Column("owner_id", sa.String(256), nullable=True),
    )
    op.create_index("ix_experiments_owner_id", "experiments", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_experiments_owner_id", table_name="experiments")
    op.drop_column("experiments", "owner_id")
