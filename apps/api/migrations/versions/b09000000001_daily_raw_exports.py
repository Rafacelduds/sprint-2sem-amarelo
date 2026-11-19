"""Publicação diária dos brutos US09.

Revision ID: b09000000001
Revises: 20261118_0005
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b09000000001"
down_revision = "20261118_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_raw_exports",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("reference", postgresql.JSONB(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("signature", sa.String(), nullable=False),
        sa.Column("snapshots", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("daily_raw_exports")
