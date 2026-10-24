"""signal origin and telegram history marker

Revision ID: d5origin03c042
Revises: c4feed01a024
Create Date: 2026-10-23 01:05:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "d5origin03c042"
down_revision = "c4feed01a024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "signals",
        sa.Column("origin", sa.String(length=16), server_default="sample", nullable=False),
    )
    op.create_check_constraint(
        "ck_signals_origin",
        "signals",
        "origin IN ('sample', 'channel')",
    )
    op.add_column(
        "source_feeds",
        sa.Column("history_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_feeds", "history_synced_at")
    op.drop_constraint("ck_signals_origin", "signals", type_="check")
    op.drop_column("signals", "origin")
