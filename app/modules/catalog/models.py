from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    FetchedValue,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

NUMERIC_SPECIFICATION_KEYS = (
    "ram_gb",
    "ssd_gb",
    "storage_gb",
    "vram_gb",
    "display_size_in",
    "resolution_width_px",
    "resolution_height_px",
    "refresh_rate_hz",
    "battery_capacity_mah",
    "camera_mp",
    "weight_g",
    "volume_l",
    "load_capacity_kg",
    "power_w",
)

_numeric_specification_pattern = "|".join(NUMERIC_SPECIFICATION_KEYS)

SEARCH_CONFIGURATION = "'pg_catalog.russian'::regconfig"
SEARCH_TRANSLATION_FROM = "Ёё‐‑‒–—−"
SEARCH_TRANSLATION_TO = "Ее------"
SKU_SEPARATOR_PATTERN = "[^[:alnum:]]+"


def _weighted_search_terms(expression: str, weight: str) -> str:
    return (
        f"setweight(to_tsvector({SEARCH_CONFIGURATION}, "
        f"translate({expression}, '{SEARCH_TRANSLATION_FROM}', '{SEARCH_TRANSLATION_TO}')), '{weight}')"
    )


PRODUCT_SEARCH_VECTOR = " || ".join(
    (
        _weighted_search_terms("name || ' ' || sku", "A"),
        _weighted_search_terms("left(specifications::text, 8192)", "B"),
        _weighted_search_terms("left(description, 16000)", "C"),
    )
)
DOCUMENT_SEARCH_VECTOR = " || ".join(
    (
        _weighted_search_terms("title", "A"),
        _weighted_search_terms("left(content, 65536)", "C"),
    )
)
PRODUCT_SEARCH_SKU = f"regexp_replace(lower(sku), '{SKU_SEPARATOR_PATTERN}', '', 'g')"


class DocumentType(StrEnum):
    PRODUCT_DESCRIPTION = "product_description"
    TECHNICAL_SPECIFICATION = "technical_specification"
    PRODUCT_MANUAL = "product_manual"
    FREQUENTLY_ASKED_QUESTIONS = "frequently_asked_questions"


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
        CheckConstraint("id <> parent_id", name="parent_not_self"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    parent: Mapped[Category | None] = relationship(remote_side=[id], lazy="raise")


class Brand(Base):
    __tablename__ = "brands"
    __table_args__ = (CheckConstraint("btrim(name) <> ''", name="name_not_blank"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        CheckConstraint("btrim(sku) <> '' AND sku = btrim(sku)", name="sku_format"),
        CheckConstraint("price >= 0 AND price <> 'NaN'::numeric", name="price_valid"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("stock_quantity >= 0", name="stock_quantity_non_negative"),
        CheckConstraint("rating BETWEEN 0 AND 5", name="rating_range"),
        CheckConstraint("jsonb_typeof(specifications) = 'object'", name="specifications_object"),
        CheckConstraint(
            f"""CASE WHEN jsonb_typeof(specifications) = 'object' THEN
                NOT jsonb_path_exists(specifications, '$.keyvalue()
                    ? (@.key like_regex "^({_numeric_specification_pattern})$")
                    ? (@.value.type() != "number" || @.value <= 0)')
                ELSE true END""",
            name="specifications_numeric_values",
        ),
        Index("ix_products_category_id_price", "category_id", "price"),
        Index("ix_products_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_products_search_sku", "search_sku"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    category_id: Mapped[UUID] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    brand_id: Mapped[UUID] = mapped_column(ForeignKey("brands.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(250))
    sku: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), index=True)
    currency: Mapped[str] = mapped_column(String(3), server_default="RUB")
    stock_quantity: Mapped[int] = mapped_column(server_default=text("0"))
    specifications: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), server_default=text("'{}'::jsonb")
    )
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue()
    )
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed(literal_column(PRODUCT_SEARCH_VECTOR), persisted=True), deferred=True
    )
    search_sku: Mapped[str] = mapped_column(
        Text, Computed(literal_column(PRODUCT_SEARCH_SKU), persisted=True), deferred=True
    )

    category: Mapped[Category] = relationship(lazy="raise")
    brand: Mapped[Brand] = relationship(lazy="raise")
    documents: Mapped[list[ProductDocument]] = relationship(
        back_populates="product",
        cascade="save-update, merge, delete, delete-orphan",
        lazy="raise",
        passive_deletes=True,
    )


class ProductDocument(Base):
    __tablename__ = "product_documents"
    __table_args__ = (
        CheckConstraint("btrim(title) <> ''", name="title_not_blank"),
        CheckConstraint("btrim(content) <> ''", name="content_not_blank"),
        CheckConstraint("btrim(source) <> ''", name="source_not_blank"),
        Index("ix_product_documents_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    document_type: Mapped[DocumentType] = mapped_column(
        Enum(
            DocumentType,
            name="document_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=list,
            length=32,
        )
    )
    title: Mapped[str] = mapped_column(String(250))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue()
    )
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed(literal_column(DOCUMENT_SEARCH_VECTOR), persisted=True), deferred=True
    )

    product: Mapped[Product] = relationship(back_populates="documents", lazy="raise")
