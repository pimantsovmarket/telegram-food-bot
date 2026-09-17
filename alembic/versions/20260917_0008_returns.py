"""Add returns data layer."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_0008"
down_revision: str | None = "20260917_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "returns",
        sa.Column("return_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("cabinet_id", sa.Integer(), sa.ForeignKey("cabinets.id"), primary_key=True, autoincrement=False),
        sa.Column("source_id", sa.BigInteger(), nullable=True),
        sa.Column("schema", sa.String(length=10), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column("order_number", sa.String(length=255), nullable=True),
        sa.Column("posting_number", sa.String(length=255), nullable=True),
        sa.Column("sku", sa.BigInteger(), nullable=True),
        sa.Column("offer_id", sa.String(length=255), nullable=True),
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status_id", sa.Integer(), nullable=True),
        sa.Column("status_code", sa.String(length=100), nullable=True),
        sa.Column("status_name", sa.String(length=255), nullable=True),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("return_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_moment", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["cabinet_id", "product_id"],
            ["products.cabinet_id", "products.product_id"],
            name="fk_returns_product",
        ),
        sa.UniqueConstraint("cabinet_id", "return_id", name="uq_returns_cabinet_return"),
    )
    op.create_index("ix_returns_cabinet_schema", "returns", ["cabinet_id", "schema"])
    op.create_index("ix_returns_posting_number", "returns", ["posting_number"])
    op.create_index("ix_returns_sku", "returns", ["sku"])


def downgrade() -> None:
    op.drop_index("ix_returns_sku", table_name="returns")
    op.drop_index("ix_returns_posting_number", table_name="returns")
    op.drop_index("ix_returns_cabinet_schema", table_name="returns")
    op.drop_table("returns")
