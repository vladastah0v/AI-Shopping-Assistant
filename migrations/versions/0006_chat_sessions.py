"""Store anonymous sessions and conversation messages."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("owner_token_hash", sa.String(64), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("state", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_sessions")),
        sa.CheckConstraint("owner_token_hash ~ '^[0-9a-f]{64}$'", name="owner_hash_format"),
        sa.CheckConstraint("revision >= 0", name="revision_non_negative"),
        sa.CheckConstraint("jsonb_typeof(state) = 'object'", name="state_object"),
    )
    op.create_index(
        "ix_chat_sessions_owner_updated", "chat_sessions", ["owner_token_hash", "updated_at"]
    )
    op.create_index("ix_chat_sessions_expires_at", "chat_sessions", ["expires_at"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(160), nullable=True),
        sa.Column("metadata", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            ondelete="CASCADE",
            name=op.f("fk_chat_messages_session_id_chat_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
        sa.UniqueConstraint("session_id", "position", name="uq_chat_messages_session_position"),
        sa.CheckConstraint("role IN ('user', 'assistant', 'tool')", name="role_allowed"),
        sa.CheckConstraint("position >= 1", name="position_positive"),
        sa.CheckConstraint("char_length(content) BETWEEN 1 AND 16000", name="content_length"),
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'shopping_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON chat_sessions, chat_messages TO shopping_app;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
