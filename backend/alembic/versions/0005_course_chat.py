"""Course conversations and vector indexing metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("knowledge_chunks", sa.Column("embedding_dimensions", sa.Integer()))
    op.add_column("knowledge_chunks", sa.Column("embedding_error", sa.String(255)))
    op.add_column("knowledge_chunks", sa.Column("embedding_retry_at", sa.DateTime(timezone=True)))
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "course_id",
            sa.String(36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_token", sa.String(36)),
        sa.Column("processing_started_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_conversations_course_id", "conversations", ["course_id"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("supplement", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("retrieval_mode", sa.String(16)),
        sa.Column("model", sa.String(128)),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", "sequence"),
        sa.UniqueConstraint("conversation_id", "request_id", "role"),
    )
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])


def downgrade():
    op.drop_table("chat_messages")
    op.drop_table("conversations")
    op.drop_column("knowledge_chunks", "embedding_retry_at")
    op.drop_column("knowledge_chunks", "embedding_error")
    op.drop_column("knowledge_chunks", "embedding_dimensions")
