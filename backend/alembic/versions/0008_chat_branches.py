"""Independent branch conversations with bounded context snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "conversations",
        sa.Column(
            "parent_conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "parent_message_id",
            sa.String(36),
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE", name="fk_branch_parent_message"),
        ),
    )
    op.add_column("conversations", sa.Column("branch_request_id", sa.String(36)))
    op.add_column(
        "conversations", sa.Column("anchor_text", sa.Text(), nullable=False, server_default="")
    )
    op.add_column("conversations", sa.Column("context_mode", sa.String(16)))
    op.add_column(
        "conversations",
        sa.Column("context_snapshot", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_conversations_parent_conversation_id", "conversations", ["parent_conversation_id"]
    )
    op.create_unique_constraint(
        "uq_conversations_parent_request",
        "conversations",
        ["parent_conversation_id", "branch_request_id"],
    )


def downgrade():
    op.drop_constraint("uq_conversations_parent_request", "conversations", type_="unique")
    op.drop_index("ix_conversations_parent_conversation_id", "conversations")
    op.drop_constraint("fk_branch_parent_message", "conversations", type_="foreignkey")
    op.drop_column("conversations", "context_snapshot")
    op.drop_column("conversations", "context_mode")
    op.drop_column("conversations", "anchor_text")
    op.drop_column("conversations", "branch_request_id")
    op.drop_column("conversations", "parent_message_id")
    op.drop_column("conversations", "parent_conversation_id")
