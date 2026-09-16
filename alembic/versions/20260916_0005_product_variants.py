"""Add optional product variant details."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260916_0005"
down_revision: str | None = "20260915_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("sku", sa.BigInteger(), nullable=True))
    op.add_column("products", sa.Column("size", sa.String(length=100), nullable=True))
    op.add_column("products", sa.Column("color", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "color")
    op.drop_column("products", "size")
    op.drop_column("products", "sku")
