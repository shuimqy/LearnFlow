"""Account model settings and embeddings kept separately while rebuilding."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_profiles_user_id", "model_profiles", ["user_id"])
    op.create_table(
        "account_models",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("llm_id", sa.String(36), sa.ForeignKey("model_profiles.id", ondelete="SET NULL")),
        sa.Column(
            "embedding_id", sa.String(36), sa.ForeignKey("model_profiles.id", ondelete="SET NULL")
        ),
        sa.Column(
            "pending_embedding_id",
            sa.String(36),
            sa.ForeignKey("model_profiles.id", ondelete="SET NULL"),
        ),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "knowledge_embeddings",
        sa.Column(
            "chunk_id",
            sa.String(36),
            sa.ForeignKey("knowledge_chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("model_profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("embedding", Vector().with_variant(sa.JSON(), "sqlite")),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.String(255)),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("embedded_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_knowledge_embeddings_profile_id", "knowledge_embeddings", ["profile_id"])
    op.add_column("knowledge_chunks", sa.Column("embedding_fingerprint", sa.String(64)))


def downgrade():
    op.drop_column("knowledge_chunks", "embedding_fingerprint")
    op.drop_table("knowledge_embeddings")
    op.drop_table("account_models")
    op.drop_table("model_profiles")
