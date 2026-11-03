"""Persist model opinions and proposal execution results."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("knowledge_proposals", sa.Column("processing_token", sa.String(36)))
    op.add_column(
        "knowledge_proposals", sa.Column("processing_started_at", sa.DateTime(timezone=True))
    )
    op.add_column("knowledge_proposals", sa.Column("llm_review", sa.JSON()))


def downgrade():
    op.drop_column("knowledge_proposals", "llm_review")
    op.drop_column("knowledge_proposals", "processing_started_at")
    op.drop_column("knowledge_proposals", "processing_token")
