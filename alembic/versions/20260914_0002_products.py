"""Add products catalog table."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260914_0002"
down_revision: str | None = "20260914_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cabinet_id", sa.Integer(), sa.ForeignKey("cabinets.id"), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("offer_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("cabinet_id", "product_id", name="uq_products_cabinet_product"),
    )
    op.create_index("ix_products_cabinet_id", "products", ["cabinet_id"])


def downgrade() -> None:
    op.drop_index("ix_products_cabinet_id", table_name="products")
    op.drop_table("products")
