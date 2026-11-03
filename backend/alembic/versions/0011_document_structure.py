"""Chapters, exercise regions and workbook image snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "document_structures",
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("run_id", sa.String(36)),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "chapters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("start_page", sa.Integer(), nullable=False),
        sa.Column("end_page", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
    )
    op.create_index("ix_chapters_document_id", "chapters", ["document_id"])
    op.create_table(
        "exercise_layouts",
        sa.Column(
            "draft_id",
            sa.String(36),
            sa.ForeignKey("extraction_drafts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("regions", sa.JSON(), nullable=False),
        sa.Column("question_type", sa.String(24), nullable=False),
        sa.Column("difficulty", sa.String(24), nullable=False),
        sa.Column("knowledge_tags", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "exercise_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "draft_id",
            sa.String(36),
            sa.ForeignKey("extraction_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("layout_version", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
    )
    op.create_index("ix_exercise_assets_draft_id", "exercise_assets", ["draft_id"])
    op.create_table(
        "workbook_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workbook_id",
            sa.String(36),
            sa.ForeignKey("workbooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("draft_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
    )
    op.create_index("ix_workbook_assets_workbook_id", "workbook_assets", ["workbook_id"])


def downgrade():
    for name in (
        "workbook_assets",
        "exercise_assets",
        "exercise_layouts",
        "chapters",
        "document_structures",
    ):
        op.drop_table(name)
