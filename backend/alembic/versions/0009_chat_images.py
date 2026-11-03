"""Private message images and their text observations."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "chat_messages", sa.Column("image_context", sa.Text(), nullable=False, server_default="")
    )
    op.create_table(
        "chat_images",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "message_id",
            sa.String(36),
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(32), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint("message_id", "position"),
    )
    op.create_index("ix_chat_images_message_id", "chat_images", ["message_id"])


def downgrade():
    op.drop_table("chat_images")
    op.drop_column("chat_messages", "image_context")
