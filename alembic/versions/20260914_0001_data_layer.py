"""Create foundation data layer tables."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260914_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cabinets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "app_state",
        sa.Column("key", sa.String(length=255), primary_key=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cabinet_id", sa.Integer(), sa.ForeignKey("cabinets.id"), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("entity", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rows_received", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_sync_runs_cabinet_id", "sync_runs", ["cabinet_id"])


def downgrade() -> None:
    op.drop_index("ix_sync_runs_cabinet_id", table_name="sync_runs")
    op.drop_table("sync_runs")
    op.drop_table("app_state")
    op.drop_table("cabinets")
