"""Relatórios públicos diários e intervalo dos novos ciclos."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261119_0006"
down_revision = "20261118_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collection_cycles", sa.Column("interval_seconds", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_cycle_interval", "collection_cycles", "interval_seconds BETWEEN 15 AND 60"
    )
    op.create_index("ix_collection_cycles_scheduled_at", "collection_cycles", ["scheduled_at"])
    op.create_table(
        "daily_reliability_reports",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("daily_reliability_reports")
    op.drop_index("ix_collection_cycles_scheduled_at", table_name="collection_cycles")
    op.drop_constraint("ck_cycle_interval", "collection_cycles", type_="check")
    op.drop_column("collection_cycles", "interval_seconds")
