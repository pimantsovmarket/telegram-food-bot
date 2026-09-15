"""Add Ozon postings and posting items tables."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260915_0004"
down_revision: str | None = "20260915_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "postings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cabinet_id", sa.Integer(), sa.ForeignKey("cabinets.id"), nullable=False),
        sa.Column("posting_number", sa.String(length=255), nullable=False),
        sa.Column("scheme", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=100), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("cabinet_id", "scheme", "posting_number", name="uq_postings_cabinet_scheme_number"),
    )
    op.create_index("ix_postings_cabinet_id", "postings", ["cabinet_id"])
    op.create_table(
        "posting_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("posting_id", sa.Integer(), sa.ForeignKey("postings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cabinet_id", sa.Integer(), sa.ForeignKey("cabinets.id"), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        sa.Column("offer_id", sa.String(length=255), nullable=False),
        sa.Column("sku", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("match_status", sa.String(length=20), nullable=False),
        sa.Column("match_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["cabinet_id", "product_id"],
            ["products.cabinet_id", "products.product_id"],
            name="fk_posting_items_product",
        ),
        sa.UniqueConstraint("posting_id", "offer_id", "sku", name="uq_posting_items_posting_offer_sku"),
    )
    op.create_index("ix_posting_items_posting_id", "posting_items", ["posting_id"])
    op.create_index("ix_posting_items_cabinet_id", "posting_items", ["cabinet_id"])


def downgrade() -> None:
    op.drop_index("ix_posting_items_cabinet_id", table_name="posting_items")
    op.drop_index("ix_posting_items_posting_id", table_name="posting_items")
    op.drop_table("posting_items")
    op.drop_index("ix_postings_cabinet_id", table_name="postings")
    op.drop_table("postings")
