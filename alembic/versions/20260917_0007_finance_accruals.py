"""Add finance accrual data layer."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_0007"
down_revision: str | None = "20260916_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "finance_accrual_types",
        sa.Column("type_id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "finance_accruals",
        sa.Column("accrual_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("cabinet_id", sa.Integer(), sa.ForeignKey("cabinets.id"), nullable=False),
        sa.Column("operation_date", sa.Date(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("posting_number", sa.String(length=255), nullable=True),
        sa.Column("total_amount", sa.Numeric(19, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_finance_accruals_cabinet_date", "finance_accruals", ["cabinet_id", "operation_date"])
    op.create_index("ix_finance_accruals_posting_number", "finance_accruals", ["posting_number"])
    op.create_table(
        "finance_accrual_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("accrual_id", sa.BigInteger(), sa.ForeignKey("finance_accruals.accrual_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku", sa.BigInteger(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("seller_price", sa.Numeric(19, 6), nullable=True),
        sa.Column("sale_price", sa.Numeric(19, 6), nullable=True),
        sa.Column("sale_amount", sa.Numeric(19, 6), nullable=True),
        sa.Column("sale_commission", sa.Numeric(19, 6), nullable=True),
        sa.Column("commission", sa.Numeric(19, 6), nullable=True),
        sa.Column("commission_ratio", sa.Numeric(19, 6), nullable=True),
        sa.Column("coinvestment", sa.Numeric(19, 6), nullable=True),
        sa.Column("bonus", sa.Numeric(19, 6), nullable=True),
    )
    op.create_index("ix_finance_accrual_items_accrual_sku", "finance_accrual_items", ["accrual_id", "sku"])
    op.create_index("ix_products_sku", "products", ["sku"])
    op.create_table(
        "finance_accrual_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("accrual_id", sa.BigInteger(), sa.ForeignKey("finance_accruals.accrual_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku", sa.BigInteger(), nullable=True),
        sa.Column("type_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(19, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
    )
    op.create_index("ix_finance_accrual_components_accrual", "finance_accrual_components", ["accrual_id"])
    op.create_index("ix_finance_accrual_components_type", "finance_accrual_components", ["type_id"])
    op.create_index("ix_finance_accrual_components_sku", "finance_accrual_components", ["sku"])


def downgrade() -> None:
    op.drop_index("ix_finance_accrual_components_sku", table_name="finance_accrual_components")
    op.drop_index("ix_finance_accrual_components_type", table_name="finance_accrual_components")
    op.drop_index("ix_finance_accrual_components_accrual", table_name="finance_accrual_components")
    op.drop_table("finance_accrual_components")
    op.drop_index("ix_products_sku", table_name="products")
    op.drop_index("ix_finance_accrual_items_accrual_sku", table_name="finance_accrual_items")
    op.drop_table("finance_accrual_items")
    op.drop_index("ix_finance_accruals_posting_number", table_name="finance_accruals")
    op.drop_index("ix_finance_accruals_cabinet_date", table_name="finance_accruals")
    op.drop_table("finance_accruals")
    op.drop_table("finance_accrual_types")
