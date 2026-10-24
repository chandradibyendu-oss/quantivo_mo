"""Intraday to 7 days expires seven days after the post.

Revision ID: g8seven06f3a
Revises: f7clocks05e29
Create Date: 2026-10-24 14:15:00.000000

"""

from datetime import timedelta

import sqlalchemy as sa
from alembic import op
from app.modules.feeds.equity_parser import seven_day_horizon

revision = "g8seven06f3a"
down_revision = "f7clocks05e29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _set_expiry(days=7)


def downgrade() -> None:
    _set_expiry(days=30)


def _set_expiry(*, days: int) -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, horizon_raw, published_at FROM signals")
    ).mappings()
    for row in rows:
        if not seven_day_horizon(row["horizon_raw"] or ""):
            continue
        connection.execute(
            sa.text("UPDATE signals SET expires_at = :expires_at WHERE id = :id"),
            {"id": row["id"], "expires_at": row["published_at"] + timedelta(days=days)},
        )
