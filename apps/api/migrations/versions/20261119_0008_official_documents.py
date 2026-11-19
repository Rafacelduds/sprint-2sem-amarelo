"""US05: catálogo documental vinculado aos PDFs originais."""

import sqlalchemy as sa
from alembic import op

revision = "20261119_0008"
down_revision = "20261119_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "official_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "raw_object_id", sa.Uuid(), sa.ForeignKey("raw_objects.id"), nullable=False, unique=True
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("agency", sa.String(300), nullable=True),
        sa.Column("document_type", sa.String(30), nullable=False),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("source", sa.String(2000), nullable=False),
        sa.Column("notes", sa.String(4000), nullable=True),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("catalogued_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "document_type IN ('contrato', 'aditivo', 'procedimento', 'ficha_indicador')",
            name="ck_official_documents_type",
        ),
    )
    op.create_index("ix_official_documents_document_type", "official_documents", ["document_type"])
    op.create_index("ix_official_documents_document_date", "official_documents", ["document_date"])


def downgrade() -> None:
    op.drop_table("official_documents")
