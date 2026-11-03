"""Page extraction results and drafts awaiting review."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("processing_tasks", sa.Column("run_id", sa.String(36)))
    op.create_table(
        "page_extractions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("model", sa.String(128)),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("document_id", "page_number"),
    )
    op.create_index("ix_page_extractions_document_id", "page_extractions", ["document_id"])
    op.create_table(
        "extraction_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "extraction_id",
            sa.String(36),
            sa.ForeignKey("page_extractions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("example", sa.JSON()),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("formulas", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "knowledge_id", sa.String(36), sa.ForeignKey("knowledge_points.id", ondelete="SET NULL")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("extraction_id", "position"),
    )
    op.create_index("ix_extraction_drafts_extraction_id", "extraction_drafts", ["extraction_id"])


def downgrade():
    op.drop_table("extraction_drafts")
    op.drop_table("page_extractions")
    op.drop_column("processing_tasks", "run_id")
