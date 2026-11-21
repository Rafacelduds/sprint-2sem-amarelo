"""Keep pending retries when the backup worker stops normally."""

import sqlalchemy as sa
from alembic import op

revision = "20261120_0011"
down_revision = "20261120_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "backup_worker", "heartbeat_at", existing_type=sa.DateTime(timezone=True), nullable=True
    )


def downgrade() -> None:
    # A versão anterior representa inatividade pela ausência da linha.
    # Recusar downgrade com retry pendente evita descartar silenciosamente a agenda.
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT count(*) FROM backup_worker WHERE heartbeat_at IS NULL AND retry_at IS NOT NULL"
        )
    ):
        raise ValueError("resolva os retries pendentes antes de reverter a migração")
    connection.execute(sa.text("DELETE FROM backup_worker WHERE heartbeat_at IS NULL"))
    op.alter_column(
        "backup_worker", "heartbeat_at", existing_type=sa.DateTime(timezone=True), nullable=False
    )
