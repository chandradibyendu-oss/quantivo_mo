"""finished one-minute bars

Revision ID: i0bars08h5c
Revises: h9intent07g4b
Create Date: 2026-10-26 23:50:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "i0bars08h5c"
down_revision = "h9intent07g4b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "minute_bars",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("high", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("low", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("close", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "opened_at", name=op.f("pk_minute_bars")),
    )
    op.create_index(
        "ix_minute_bars_symbol_session_date",
        "minute_bars",
        ["symbol", "session_date"],
    )
    op.create_table(
        "minute_bar_days",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "session_date", name=op.f("pk_minute_bar_days")),
    )


def downgrade() -> None:
    op.drop_table("minute_bar_days")
    op.drop_index("ix_minute_bars_symbol_session_date", table_name="minute_bars")
    op.drop_table("minute_bars")
