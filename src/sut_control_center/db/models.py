from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Cabinet(Base):
    __tablename__ = "cabinets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    sync_runs: Mapped[list[SyncRun]] = relationship(back_populates="cabinet")
    products: Mapped[list[Product]] = relationship(back_populates="cabinet")
    stocks: Mapped[list[Stock]] = relationship(back_populates="cabinet")
    postings: Mapped[list[Posting]] = relationship(back_populates="cabinet")
    returns: Mapped[list[Return]] = relationship(back_populates="cabinet")


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[int] = mapped_column(ForeignKey("cabinets.id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    entity: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)

    cabinet: Mapped[Cabinet] = relationship(back_populates="sync_runs")


class AppState(Base):
    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value_json: Mapped[dict[str, Any] | list[Any] | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("cabinet_id", "product_id", name="uq_products_cabinet_product"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[int] = mapped_column(ForeignKey("cabinets.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    offer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    sku: Mapped[int | None] = mapped_column(BigInteger, index=True)
    size: Mapped[str | None] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    cabinet: Mapped[Cabinet] = relationship(back_populates="products")


class ProductReplenishmentParameters(Base):
    __tablename__ = "product_replenishment_parameters"
    __table_args__ = (
        ForeignKeyConstraint(
            ["cabinet_id", "product_id"],
            ["products.cabinet_id", "products.product_id"],
            name="fk_replenishment_parameters_product",
        ),
        CheckConstraint("lead_time_days >= 0", name="ck_replenishment_lead_time_nonnegative"),
        CheckConstraint("safety_stock_days >= 0", name="ck_replenishment_safety_stock_nonnegative"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_replenishment_effective_interval",
        ),
        Index(
            "ix_replenishment_parameters_product_effective",
            "cabinet_id",
            "product_id",
            "effective_from",
        ),
        Index(
            "uq_replenishment_parameters_active",
            "cabinet_id",
            "product_id",
            unique=True,
            sqlite_where=text("effective_to IS NULL"),
            postgresql_where=text("effective_to IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[int] = mapped_column(ForeignKey("cabinets.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    safety_stock_days: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

class Stock(Base):
    __tablename__ = "stocks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["cabinet_id", "product_id"],
            ["products.cabinet_id", "products.product_id"],
            name="fk_stocks_product",
        ),
        UniqueConstraint(
            "cabinet_id",
            "product_id",
            "stock_type",
            "sku",
            name="uq_stocks_cabinet_product_type_sku",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[int] = mapped_column(ForeignKey("cabinets.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    offer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stock_type: Mapped[str] = mapped_column(String(50), nullable=False)
    sku: Mapped[int] = mapped_column(BigInteger, nullable=False)
    present: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    cabinet: Mapped[Cabinet] = relationship(back_populates="stocks")


class Posting(Base):
    __tablename__ = "postings"
    __table_args__ = (
        UniqueConstraint("cabinet_id", "scheme", "posting_number", name="uq_postings_cabinet_scheme_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[int] = mapped_column(ForeignKey("cabinets.id"), nullable=False, index=True)
    posting_number: Mapped[str] = mapped_column(String(255), nullable=False)
    scheme: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(100), nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    cabinet: Mapped[Cabinet] = relationship(back_populates="postings")
    items: Mapped[list[PostingItem]] = relationship(back_populates="posting", cascade="all, delete-orphan")


class PostingItem(Base):
    __tablename__ = "posting_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["cabinet_id", "product_id"],
            ["products.cabinet_id", "products.product_id"],
            name="fk_posting_items_product",
        ),
        UniqueConstraint("posting_id", "offer_id", "sku", name="uq_posting_items_posting_offer_sku"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    posting_id: Mapped[int] = mapped_column(ForeignKey("postings.id", ondelete="CASCADE"), nullable=False, index=True)
    cabinet_id: Mapped[int] = mapped_column(ForeignKey("cabinets.id"), nullable=False, index=True)
    product_id: Mapped[int | None] = mapped_column(BigInteger)
    offer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    match_status: Mapped[str] = mapped_column(String(20), nullable=False)
    match_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    posting: Mapped[Posting] = relationship(back_populates="items")


class FinanceAccrualType(Base):
    __tablename__ = "finance_accrual_types"

    type_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class FinanceAccrual(Base):
    __tablename__ = "finance_accruals"
    __table_args__ = (
        Index("ix_finance_accruals_cabinet_date", "cabinet_id", "operation_date"),
        Index("ix_finance_accruals_posting_number", "posting_number"),
    )

    accrual_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    cabinet_id: Mapped[int] = mapped_column(ForeignKey("cabinets.id"), nullable=False)
    operation_date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    posting_number: Mapped[str | None] = mapped_column(String(255))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(19, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class FinanceAccrualItem(Base):
    __tablename__ = "finance_accrual_items"
    __table_args__ = (Index("ix_finance_accrual_items_accrual_sku", "accrual_id", "sku"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    accrual_id: Mapped[int] = mapped_column(ForeignKey("finance_accruals.accrual_id", ondelete="CASCADE"), nullable=False)
    sku: Mapped[int | None] = mapped_column(BigInteger)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    seller_price: Mapped[Decimal | None] = mapped_column(Numeric(19, 6))
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(19, 6))
    sale_amount: Mapped[Decimal | None] = mapped_column(Numeric(19, 6))
    sale_commission: Mapped[Decimal | None] = mapped_column(Numeric(19, 6))
    commission: Mapped[Decimal | None] = mapped_column(Numeric(19, 6))
    commission_ratio: Mapped[Decimal | None] = mapped_column(Numeric(19, 6))
    coinvestment: Mapped[Decimal | None] = mapped_column(Numeric(19, 6))
    bonus: Mapped[Decimal | None] = mapped_column(Numeric(19, 6))


class FinanceAccrualComponent(Base):
    __tablename__ = "finance_accrual_components"
    __table_args__ = (
        Index("ix_finance_accrual_components_accrual", "accrual_id"),
        Index("ix_finance_accrual_components_type", "type_id"),
        Index("ix_finance_accrual_components_sku", "sku"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    accrual_id: Mapped[int] = mapped_column(ForeignKey("finance_accruals.accrual_id", ondelete="CASCADE"), nullable=False)
    sku: Mapped[int | None] = mapped_column(BigInteger)
    type_id: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class Return(Base):
    __tablename__ = "returns"
    __table_args__ = (
        UniqueConstraint("cabinet_id", "return_id", name="uq_returns_cabinet_return"),
        ForeignKeyConstraint(
            ["cabinet_id", "product_id"],
            ["products.cabinet_id", "products.product_id"],
            name="fk_returns_product",
        ),
        Index("ix_returns_cabinet_schema", "cabinet_id", "schema"),
        Index("ix_returns_posting_number", "posting_number"),
        Index("ix_returns_sku", "sku"),
    )

    return_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    cabinet_id: Mapped[int] = mapped_column(ForeignKey("cabinets.id"), primary_key=True, autoincrement=False)
    source_id: Mapped[int | None] = mapped_column(BigInteger)
    schema: Mapped[str] = mapped_column(String(10), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    order_id: Mapped[int | None] = mapped_column(BigInteger)
    order_number: Mapped[str | None] = mapped_column(String(255))
    posting_number: Mapped[str | None] = mapped_column(String(255))
    sku: Mapped[int | None] = mapped_column(BigInteger)
    offer_id: Mapped[str | None] = mapped_column(String(255))
    product_id: Mapped[int | None] = mapped_column(BigInteger)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status_id: Mapped[int | None] = mapped_column(Integer)
    status_code: Mapped[str | None] = mapped_column(String(100))
    status_name: Mapped[str | None] = mapped_column(String(255))
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    return_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    final_moment: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    cabinet: Mapped[Cabinet] = relationship(back_populates="returns")
