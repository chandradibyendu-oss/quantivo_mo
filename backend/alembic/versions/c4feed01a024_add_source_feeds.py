"""add source feeds and signal match status

Revision ID: c4feed01a024
Revises: 51909777e005
Create Date: 2026-10-23 00:40:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c4feed01a024"
down_revision = "51909777e005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "signals",
        sa.Column("match_status", sa.String(length=16), server_default="matched", nullable=False),
    )
    op.create_check_constraint(
        "ck_signals_match_status",
        "signals",
        "match_status IN ('matched', 'unmatched', 'ambiguous')",
    )
    op.create_table(
        "source_feeds",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_channel_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('none', 'telegram', 'http_api')", name="ck_source_feeds_kind"),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_source_feeds_status"),
        sa.ForeignKeyConstraint(
            ["source_channel_id"],
            ["source_channels.id"],
            name="fk_source_feeds_source_channel_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_feeds"),
        sa.UniqueConstraint("source_channel_id", name="uq_source_feeds_source_channel_id"),
    )


def downgrade() -> None:
    op.drop_table("source_feeds")
    op.drop_constraint("ck_signals_match_status", "signals", type_="check")
    op.drop_column("signals", "match_status")
