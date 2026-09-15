"""Add current product stocks table."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260915_0003"
down_revision: str | None = "20260914_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cabinet_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("offer_id", sa.String(length=255), nullable=False),
        sa.Column("stock_type", sa.String(length=50), nullable=False),
        sa.Column("sku", sa.BigInteger(), nullable=False),
        sa.Column("present", sa.Integer(), nullable=False),
        sa.Column("reserved", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["cabinet_id"], ["cabinets.id"]),
        sa.ForeignKeyConstraint(
            ["cabinet_id", "product_id"],
            ["products.cabinet_id", "products.product_id"],
            name="fk_stocks_product",
        ),
        sa.UniqueConstraint(
            "cabinet_id",
            "product_id",
            "stock_type",
            "sku",
            name="uq_stocks_cabinet_product_type_sku",
        ),
    )
    op.create_index("ix_stocks_cabinet_id", "stocks", ["cabinet_id"])


def downgrade() -> None:
    op.drop_index("ix_stocks_cabinet_id", table_name="stocks")
    op.drop_table("stocks")
