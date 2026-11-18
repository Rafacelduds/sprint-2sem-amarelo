"""US32: pontos de recuperação, recibos e limpeza auditável da inbox."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b32000000001"
down_revision: str | None = "b12000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("collection_snapshots", "body", nullable=True)
    op.add_column("collection_snapshots", sa.Column("body_purged_at", sa.DateTime(timezone=True)))
    op.create_table(
        "backup_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference", postgresql.JSONB(), nullable=False),
        sa.Column("dump_reference", postgresql.JSONB(), nullable=False),
        sa.Column("expired_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "backup_receipts",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("backup_id", sa.Uuid(), sa.ForeignKey("backup_runs.id"), nullable=False),
        sa.Column("primary_reference", postgresql.JSONB(), nullable=False),
        sa.Column("backup_reference", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    # Não fabricar bytes para desfazer a limpeza. Restaurar corpos antes do downgrade.
    op.alter_column("collection_snapshots", "body", nullable=False)
    op.drop_column("collection_snapshots", "body_purged_at")
    op.drop_table("backup_receipts")
    op.drop_table("backup_runs")
