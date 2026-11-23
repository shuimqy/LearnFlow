"""Store large PDF sizes."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("documents", "size_bytes", existing_type=sa.Integer(), type_=sa.BigInteger())


def downgrade():
    op.alter_column("documents", "size_bytes", existing_type=sa.BigInteger(), type_=sa.Integer())
