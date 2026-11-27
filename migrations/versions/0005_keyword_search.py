"""Index catalog text with PostgreSQL full-text search."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _weighted_terms(expression: str, weight: str) -> str:
    return (
        "setweight(to_tsvector('pg_catalog.russian'::regconfig, "
        f"translate({expression}, 'Ёё‐‑‒–—−', 'Ее------')), '{weight}')"
    )


def upgrade() -> None:
    product_vector = " || ".join(
        (
            _weighted_terms("name || ' ' || sku", "A"),
            _weighted_terms("left(specifications::text, 8192)", "B"),
            _weighted_terms("left(description, 16000)", "C"),
        )
    )
    document_vector = " || ".join(
        (
            _weighted_terms("title", "A"),
            _weighted_terms("left(content, 65536)", "C"),
        )
    )

    for table, expression in (("products", product_vector), ("product_documents", document_vector)):
        op.add_column(
            table,
            sa.Column(
                "search_vector",
                TSVECTOR(),
                sa.Computed(sa.literal_column(expression), persisted=True),
                nullable=False,
            ),
        )
        op.create_index(
            f"ix_{table}_search_vector", table, ["search_vector"], postgresql_using="gin"
        )

    op.add_column(
        "products",
        sa.Column(
            "search_sku",
            sa.Text(),
            sa.Computed(
                sa.literal_column("regexp_replace(lower(sku), '[^[:alnum:]]+', '', 'g')"),
                persisted=True,
            ),
            nullable=False,
        ),
    )
    op.create_index("ix_products_search_sku", "products", ["search_sku"])


def downgrade() -> None:
    op.drop_index("ix_products_search_sku", table_name="products")
    op.drop_column("products", "search_sku")
    for table in ("product_documents", "products"):
        op.drop_index(f"ix_{table}_search_vector", table_name=table)
        op.drop_column(table, "search_vector")
