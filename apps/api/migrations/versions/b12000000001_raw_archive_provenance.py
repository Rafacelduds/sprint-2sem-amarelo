"""US12: catálogo de brutos e manifestos de processamento."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b12000000001"
down_revision: str | None = "7ad978e014e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "raw_objects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("snapshot_id", sa.Uuid(), sa.ForeignKey("collection_snapshots.id"), unique=True),
        sa.Column("key", sa.String(), nullable=False, unique=True),
        sa.Column("reference", postgresql.JSONB(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "processing_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("reference", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("processing_runs")
    op.drop_table("raw_objects")
