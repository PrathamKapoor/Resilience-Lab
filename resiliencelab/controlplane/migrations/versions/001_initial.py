"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiments",
        sa.Column("experiment_id", sa.String(256), primary_key=True),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("config_yaml", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.String(128), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="CREATED", index=True),
        sa.Column("artifact_path", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_experiments_status_created", "experiments", ["status", "created_at"])

    op.create_table(
        "runs",
        sa.Column("run_id", sa.String(512), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.String(256),
            sa.ForeignKey("experiments.experiment_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("run_index", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="QUEUED", index=True),
        sa.Column("artifact_path", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_runs_experiment_status", "runs", ["experiment_id", "status"])

    op.create_table(
        "experiment_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "experiment_id",
            sa.String(256),
            sa.ForeignKey("experiments.experiment_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("run_id", sa.String(512), nullable=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("timestamp", sa.Float(), nullable=False),
        sa.Column("elapsed", sa.Float(), nullable=True),
        sa.Column("target_service", sa.String(256), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_events_experiment_type", "experiment_events", ["experiment_id", "event_type"]
    )


def downgrade() -> None:
    op.drop_table("experiment_events")
    op.drop_table("runs")
    op.drop_table("experiments")
