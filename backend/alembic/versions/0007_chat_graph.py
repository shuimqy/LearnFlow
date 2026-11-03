"""LangGraph PostgresSaver 3.2 schema and course conversation ownership."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chat_messages", sa.Column("workflow_stage", sa.String(24)))
    op.create_table(
        "chat_graph_threads",
        sa.Column("thread_id", sa.String(160), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("run_id", sa.String(36), nullable=False),
    )
    json_type = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table("checkpoint_migrations", sa.Column("v", sa.Integer(), primary_key=True))
    op.create_table(
        "checkpoints",
        sa.Column(
            "thread_id",
            sa.Text(),
            sa.ForeignKey("chat_graph_threads.thread_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("checkpoint_ns", sa.Text(), primary_key=True, server_default=""),
        sa.Column("checkpoint_id", sa.Text(), primary_key=True),
        sa.Column("parent_checkpoint_id", sa.Text()),
        sa.Column("type", sa.Text()),
        sa.Column("checkpoint", json_type, nullable=False),
        sa.Column("metadata", json_type, nullable=False, server_default="{}"),
    )
    op.create_table(
        "checkpoint_blobs",
        sa.Column(
            "thread_id",
            sa.Text(),
            sa.ForeignKey("chat_graph_threads.thread_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("checkpoint_ns", sa.Text(), primary_key=True, server_default=""),
        sa.Column("channel", sa.Text(), primary_key=True),
        sa.Column("version", sa.Text(), primary_key=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("blob", sa.LargeBinary()),
    )
    op.create_table(
        "checkpoint_writes",
        sa.Column(
            "thread_id",
            sa.Text(),
            sa.ForeignKey("chat_graph_threads.thread_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("checkpoint_ns", sa.Text(), primary_key=True, server_default=""),
        sa.Column("checkpoint_id", sa.Text(), primary_key=True),
        sa.Column("task_id", sa.Text(), primary_key=True),
        sa.Column("idx", sa.Integer(), primary_key=True),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("type", sa.Text()),
        sa.Column("blob", sa.LargeBinary(), nullable=False),
        sa.Column("task_path", sa.Text(), nullable=False, server_default=""),
    )
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        op.create_index(f"{table}_thread_id_idx", table, ["thread_id"])
    op.bulk_insert(
        sa.table("checkpoint_migrations", sa.column("v", sa.Integer())),
        [{"v": v} for v in range(10)],
    )


def downgrade():
    for table in (
        "checkpoint_writes",
        "checkpoint_blobs",
        "checkpoints",
        "checkpoint_migrations",
        "chat_graph_threads",
    ):
        op.drop_table(table)
    op.drop_column("chat_messages", "workflow_stage")
