"""Persist backup worker heartbeat and execution results."""

import sqlalchemy as sa
from alembic import op

revision = "20261120_0010"
down_revision = "20261120_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backup_worker",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "backup_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("backup_id", sa.Uuid(), sa.ForeignKey("backup_runs.id")),
    )


def downgrade() -> None:
    op.drop_table("backup_attempts")
    op.drop_table("backup_worker")
