"""Store the confirmed prices on an order intent.

Revision ID: h9intent07g4b
Revises: g8seven06f3a
Create Date: 2026-10-25 10:40:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "h9intent07g4b"
down_revision = "g8seven06f3a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("order_intents", sa.Column("side", sa.String(length=8), nullable=False))
    op.add_column("order_intents", sa.Column("trigger_price", sa.Numeric(18, 4), nullable=False))
    op.add_column("order_intents", sa.Column("stop_loss", sa.Numeric(18, 4), nullable=False))
    op.add_column("order_intents", sa.Column("targets", postgresql.JSONB(), nullable=False))
    op.create_check_constraint("ck_order_intents_side", "order_intents", "side IN ('BUY', 'SELL')")
    op.create_check_constraint(
        "ck_order_intents_prices_positive",
        "order_intents",
        "trigger_price > 0 AND stop_loss > 0",
    )
    op.create_index(
        "uq_order_intents_open_signal",
        "order_intents",
        ["user_id", "signal_id"],
        unique=True,
        postgresql_where=sa.text("status = 'proposed'"),
    )


def downgrade() -> None:
    op.drop_index("uq_order_intents_open_signal", table_name="order_intents")
    op.drop_constraint("ck_order_intents_prices_positive", "order_intents", type_="check")
    op.drop_constraint("ck_order_intents_side", "order_intents", type_="check")
    op.drop_column("order_intents", "targets")
    op.drop_column("order_intents", "stop_loss")
    op.drop_column("order_intents", "trigger_price")
    op.drop_column("order_intents", "side")
