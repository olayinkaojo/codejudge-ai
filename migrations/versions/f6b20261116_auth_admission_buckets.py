"""Add durable authentication admission counters; preserve all existing records."""

import sqlalchemy as sa
from alembic import op

revision = "f6b20261116"
down_revision = "b5cbbc4049b7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_rate_secrets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("secret", sa.String(64), nullable=False),
    )
    op.create_table(
        "auth_rate_buckets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("hits >= 1"),
    )
    op.create_index("ix_auth_rate_buckets_reset_at", "auth_rate_buckets", ["reset_at"])


def downgrade():
    op.drop_index("ix_auth_rate_buckets_reset_at", table_name="auth_rate_buckets")
    op.drop_table("auth_rate_buckets")
    op.drop_table("auth_rate_secrets")
