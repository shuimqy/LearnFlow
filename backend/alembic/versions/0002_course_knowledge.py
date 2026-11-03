"""Course-scoped knowledge, source references and revision history."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def key(name, target, *, nullable=False, ondelete="CASCADE"):
    return sa.Column(
        name, sa.String(36), sa.ForeignKey(target, ondelete=ondelete), nullable=nullable
    )


def identity():
    return sa.Column("id", sa.String(36), primary_key=True)


def upgrade():
    op.create_table(
        "document_pages",
        identity(),
        key("course_id", "courses.id"),
        key("document_id", "documents.id"),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "page_number"),
    )
    op.create_index("ix_document_pages_course_id", "document_pages", ["course_id"])
    op.create_table(
        "source_fragments",
        identity(),
        key("course_id", "courses.id"),
        key("page_id", "document_pages.id"),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("excluded", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.Text()),
        sa.UniqueConstraint("page_id", "char_start", "char_end"),
    )
    op.create_index("ix_source_fragments_course_id", "source_fragments", ["course_id"])
    op.create_table(
        "knowledge_points",
        identity(),
        key("course_id", "courses.id"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        key("created_by", "users.id", ondelete=None),
        key("updated_by", "users.id", ondelete=None),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_knowledge_points_course_id", "knowledge_points", ["course_id"])
    op.create_table(
        "knowledge_sources",
        identity(),
        key("knowledge_id", "knowledge_points.id"),
        key("document_id", "documents.id", nullable=True, ondelete="SET NULL"),
        key("fragment_id", "source_fragments.id", nullable=True, ondelete="SET NULL"),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_index("ix_knowledge_sources_knowledge_id", "knowledge_sources", ["knowledge_id"])
    op.create_table(
        "knowledge_revisions",
        identity(),
        key("knowledge_id", "knowledge_points.id"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        key("confirmed_by", "users.id", ondelete=None),
        sa.Column("proposal_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("knowledge_id", "version"),
    )
    op.create_table(
        "knowledge_chunks",
        identity(),
        key("course_id", "courses.id"),
        key("knowledge_id", "knowledge_points.id"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", Vector().with_variant(sa.JSON(), "sqlite")),
        sa.Column("embedding_status", sa.String(16), nullable=False),
        sa.Column("embedding_model", sa.String(128)),
        sa.Column("embedded_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("knowledge_id", "version", "position"),
    )
    op.create_index("ix_knowledge_chunks_course_id", "knowledge_chunks", ["course_id"])
    op.create_table(
        "knowledge_proposals",
        identity(),
        key("course_id", "courses.id"),
        key("knowledge_id", "knowledge_points.id"),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("proposed", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        key("created_by", "users.id", ondelete=None),
        key("resolved_by", "users.id", nullable=True, ondelete=None),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_knowledge_proposals_course_id", "knowledge_proposals", ["course_id"])


def downgrade():
    for table in [
        "knowledge_proposals",
        "knowledge_chunks",
        "knowledge_revisions",
        "knowledge_sources",
        "knowledge_points",
        "source_fragments",
        "document_pages",
    ]:
        op.drop_table(table)
