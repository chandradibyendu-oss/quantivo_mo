"""call clocks

Revision ID: f7clocks05e29
Revises: e6channel04d18
Create Date: 2026-10-24 12:30:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "f7clocks05e29"
down_revision = "e6channel04d18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "call_clocks",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("intraday_minutes", sa.Integer(), nullable=False),
        sa.Column("short_term_days", sa.Integer(), nullable=False),
        sa.Column("long_term_days", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "intraday_minutes BETWEEN 1 AND 1440",
            name=op.f("ck_call_clocks_intraday_minutes"),
        ),
        sa.CheckConstraint(
            "short_term_days BETWEEN 1 AND 365",
            name=op.f("ck_call_clocks_short_term_days"),
        ),
        sa.CheckConstraint(
            "long_term_days BETWEEN 1 AND 365",
            name=op.f("ck_call_clocks_long_term_days"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_clocks")),
    )
    op.execute(
        "INSERT INTO call_clocks "
        "(id, intraday_minutes, short_term_days, long_term_days, created_at, updated_at) "
        "VALUES (1, 30, 30, 30, now(), now())"
    )


def downgrade() -> None:
    op.drop_table("call_clocks")
