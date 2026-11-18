"""Catálogo GTFS e associação rastreável das posições (US02)."""

import sqlalchemy as sa
from alembic import op

revision = "20261118_0002"
down_revision = "34bf95c97f11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gtfs_versions",
        sa.Column("sha256", sa.String(64), primary_key=True),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("bucket", sa.String(), nullable=False),
        sa.Column("object_key", sa.String(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("coverage_basis", sa.String(), nullable=False),
        sa.Column("publisher_version", sa.String(), nullable=True),
    )
    op.create_table(
        "gtfs_captures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "version_sha256", sa.String(64), sa.ForeignKey("gtfs_versions.sha256"), nullable=False
        ),
    )
    op.create_index(
        "ix_gtfs_captures_source_captured", "gtfs_captures", ["source_id", "captured_at"]
    )
    op.add_column("vehicle_positions", sa.Column("gtfs_version_sha256", sa.String(64)))
    op.create_foreign_key(
        "fk_position_gtfs",
        "vehicle_positions",
        "gtfs_versions",
        ["gtfs_version_sha256"],
        ["sha256"],
    )
    op.add_column(
        "vehicle_positions",
        sa.Column(
            "gtfs_link_status",
            sa.String(),
            nullable=False,
            server_default="not_evaluated",
        ),
    )
    op.alter_column("vehicle_positions", "gtfs_link_status", server_default=None)


def downgrade() -> None:
    op.drop_column("vehicle_positions", "gtfs_link_status")
    op.drop_constraint("fk_position_gtfs", "vehicle_positions", type_="foreignkey")
    op.drop_column("vehicle_positions", "gtfs_version_sha256")
    op.drop_index("ix_gtfs_captures_source_captured", table_name="gtfs_captures")
    op.drop_table("gtfs_captures")
    op.drop_table("gtfs_versions")
