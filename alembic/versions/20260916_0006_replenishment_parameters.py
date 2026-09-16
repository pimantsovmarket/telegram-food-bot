"""Add versioned product replenishment parameters."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260916_0006"
down_revision: str | None = "20260916_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_replenishment_parameters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cabinet_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=False),
        sa.Column("safety_stock_days", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["cabinet_id"], ["cabinets.id"]),
        sa.ForeignKeyConstraint(
            ["cabinet_id", "product_id"],
            ["products.cabinet_id", "products.product_id"],
            name="fk_replenishment_parameters_product",
        ),
        sa.CheckConstraint("lead_time_days >= 0", name="ck_replenishment_lead_time_nonnegative"),
        sa.CheckConstraint("safety_stock_days >= 0", name="ck_replenishment_safety_stock_nonnegative"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_replenishment_effective_interval",
        ),
    )
    op.create_index(
        "ix_replenishment_parameters_product_effective",
        "product_replenishment_parameters",
        ["cabinet_id", "product_id", "effective_from"],
    )
    op.create_index(
        "uq_replenishment_parameters_active",
        "product_replenishment_parameters",
        ["cabinet_id", "product_id"],
        unique=True,
        sqlite_where=sa.text("effective_to IS NULL"),
        postgresql_where=sa.text("effective_to IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_replenishment_parameters_active", table_name="product_replenishment_parameters")
    op.drop_index("ix_replenishment_parameters_product_effective", table_name="product_replenishment_parameters")
    op.drop_table("product_replenishment_parameters")
