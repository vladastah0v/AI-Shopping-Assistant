"""record chat interactions

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-27 17:54:26.761967
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_requests",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("model_name", sa.String(length=160), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("retrieval_duration_ms", sa.Float(), nullable=False),
        sa.Column("generation_duration_ms", sa.Float(), nullable=False),
        sa.Column("total_duration_ms", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('model', 'catalog')", name=op.f("ck_llm_requests_status_allowed")
        ),
        sa.CheckConstraint(
            "retrieval_duration_ms >= 0 AND generation_duration_ms >= 0 AND total_duration_ms >= 0",
            name=op.f("ck_llm_requests_non_negative_durations"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_llm_requests_session_id_chat_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_requests")),
    )
    op.create_index(
        op.f("ix_llm_requests_session_id"), "llm_requests", ["session_id"], unique=False
    )
    op.create_table(
        "feedback",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name=op.f("ck_feedback_rating_range")),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["chat_messages.id"],
            name=op.f("fk_feedback_message_id_chat_messages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_feedback_session_id_chat_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
        sa.UniqueConstraint("message_id", name="uq_feedback_message_id"),
    )
    op.create_index(op.f("ix_feedback_session_id"), "feedback", ["session_id"], unique=False)
    op.create_table(
        "recommendation_history",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["chat_messages.id"],
            name=op.f("fk_recommendation_history_message_id_chat_messages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_recommendation_history_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_recommendation_history_session_id_chat_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendation_history")),
        sa.UniqueConstraint(
            "message_id", "product_id", name="uq_recommendation_history_message_product"
        ),
    )
    op.create_index(
        op.f("ix_recommendation_history_product_id"),
        "recommendation_history",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recommendation_history_session_id"),
        "recommendation_history",
        ["session_id"],
        unique=False,
    )

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'shopping_app') THEN
                GRANT SELECT, INSERT ON recommendation_history TO shopping_app;
                GRANT SELECT, INSERT, UPDATE ON feedback TO shopping_app;
                GRANT SELECT, INSERT, DELETE ON llm_requests TO shopping_app;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_index(op.f("ix_recommendation_history_session_id"), table_name="recommendation_history")
    op.drop_index(op.f("ix_recommendation_history_product_id"), table_name="recommendation_history")
    op.drop_table("recommendation_history")
    op.drop_index(op.f("ix_feedback_session_id"), table_name="feedback")
    op.drop_table("feedback")
    op.drop_index(op.f("ix_llm_requests_session_id"), table_name="llm_requests")
    op.drop_table("llm_requests")
