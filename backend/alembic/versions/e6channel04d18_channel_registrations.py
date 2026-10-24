"""channel registrations

Revision ID: e6channel04d18
Revises: d5origin03c042
Create Date: 2026-10-23 17:40:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "e6channel04d18"
down_revision = "d5origin03c042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_registrations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("source_channel_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
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
            "status IN ('active', 'inactive')",
            name=op.f("ck_channel_registrations_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_channel_registrations_user_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_channel_id"],
            ["source_channels.id"],
            name=op.f("fk_channel_registrations_source_channel_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channel_registrations")),
        sa.UniqueConstraint(
            "user_id",
            "source_channel_id",
            name="uq_channel_registrations_user_channel",
        ),
    )
    op.create_index(
        op.f("ix_channel_registrations_user_id"),
        "channel_registrations",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_channel_registrations_source_channel_id"),
        "channel_registrations",
        ["source_channel_id"],
        unique=False,
    )
    op.execute(
        """
        INSERT INTO channel_registrations (
            id, user_id, source_channel_id, status, created_at, updated_at
        )
        SELECT gen_random_uuid(), entitlement.user_id, channel.id, 'active', now(), now()
        FROM subscription_entitlements AS entitlement
        JOIN source_channels AS channel ON channel.scanner_id = entitlement.scanner_id
        WHERE entitlement.status = 'active' AND channel.status = 'active'
        """
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_channel_registrations_source_channel_id"),
        table_name="channel_registrations",
    )
    op.drop_index(
        op.f("ix_channel_registrations_user_id"),
        table_name="channel_registrations",
    )
    op.drop_table("channel_registrations")
