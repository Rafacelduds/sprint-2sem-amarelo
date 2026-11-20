"""Persist collection diagnostics and confirmed recovery notifications.

Revision ID: 20261120_0009
Revises: 20261119_0008
"""

import sqlalchemy as sa
from alembic import op

revision = "20261120_0009"
down_revision = "20261119_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collection_cycles", sa.Column("diagnostics", sa.JSON(), nullable=True))
    op.add_column(
        "collection_cycles",
        sa.Column("recovery_alerted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("collection_cycles", "recovery_alerted_at")
    op.drop_column("collection_cycles", "diagnostics")
