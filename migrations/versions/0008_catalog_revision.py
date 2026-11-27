"""Invalidate shared retrieval caches after catalog mutations."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None
_TABLES = (
    "categories",
    "brands",
    "products",
    "product_documents",
    "product_embeddings",
    "document_chunks",
)


def upgrade() -> None:
    op.create_table(
        "catalog_revision",
        sa.Column("singleton", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("version", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("singleton", name=op.f("pk_catalog_revision")),
        sa.CheckConstraint("singleton", name="singleton_true"),
    )
    op.execute("INSERT INTO catalog_revision DEFAULT VALUES")
    op.execute("""
        CREATE FUNCTION public.bump_catalog_revision() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            UPDATE public.catalog_revision SET version = version + 1 WHERE singleton;
            RETURN NULL;
        END
        $$
    """)
    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER bump_catalog_revision AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE "
            f"ON {table} FOR EACH STATEMENT EXECUTE FUNCTION public.bump_catalog_revision()"
        )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'shopping_app') THEN
                GRANT SELECT ON catalog_revision TO shopping_app;
            END IF;
        END $$
    """)


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TRIGGER bump_catalog_revision ON {table}")
    op.execute("DROP FUNCTION public.bump_catalog_revision()")
    op.drop_table("catalog_revision")
