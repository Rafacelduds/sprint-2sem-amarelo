"""Create initial database baseline.

Revision ID: 20261117_0001
Revises:
"""

from collections.abc import Sequence

revision: str = "20261117_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
