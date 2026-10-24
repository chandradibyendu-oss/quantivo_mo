from datetime import datetime, timedelta
from decimal import Decimal

from app.modules.signals.normalization import NormalizedSignal

PROVIDER_CODE = "mani"
SCANNER_CODE = "mani-channel"
EQUITY_CHANNEL_CODE = "equity"
SAMPLE_NOTE = "Sample signal for development. Not a market recommendation."


class MockManiAdapter:
    """In-process sample of Mani's feed. It does not call Telegram."""

    provider_code = PROVIDER_CODE

    def fetch(self, now: datetime) -> list[NormalizedSignal]:
        return [
            NormalizedSignal(
                external_ref="mani-reliance-buy",
                symbol="RELIANCE",
                exchange="NSE",
                side="BUY",
                timeframe="INTRADAY",
                product_hint="MIS",
                trigger_price=Decimal("2450.00"),
                stop_loss=Decimal("2432.00"),
                targets=(("T1", Decimal("2474.00")), ("T2", Decimal("2490.00"))),
                provider_note=SAMPLE_NOTE,
                status="active",
                published_at=now - timedelta(minutes=4),
                expires_at=now + timedelta(minutes=90),
                segment="equity",
                channel_code=EQUITY_CHANNEL_CODE,
                horizon_raw="Short term",
            ),
            NormalizedSignal(
                external_ref="mani-tcs-sell",
                symbol="TCS",
                exchange="NSE",
                side="SELL",
                timeframe="INTRADAY",
                product_hint="MIS",
                trigger_price=Decimal("4100.00"),
                stop_loss=Decimal("4145.00"),
                targets=(("T1", Decimal("4040.00")),),
                provider_note=SAMPLE_NOTE,
                status="active",
                published_at=now - timedelta(minutes=2),
                expires_at=now + timedelta(minutes=90),
                segment="equity",
                channel_code=EQUITY_CHANNEL_CODE,
                horizon_raw="Intraday to 7 days",
            ),
            NormalizedSignal(
                external_ref="mani-hdfcbank-buy",
                symbol="HDFCBANK",
                exchange="NSE",
                side="BUY",
                timeframe="INTRADAY",
                product_hint="MIS",
                trigger_price=Decimal("1650.00"),
                stop_loss=Decimal("1635.00"),
                targets=(("T1", Decimal("1675.00")),),
                provider_note=SAMPLE_NOTE,
                status="active",
                published_at=now - timedelta(minutes=45),
                expires_at=now + timedelta(minutes=30),
                segment="equity",
                channel_code=EQUITY_CHANNEL_CODE,
                horizon_raw="Intraday to 7 days",
            ),
            NormalizedSignal(
                external_ref="mani-infy-buy",
                symbol="INFY",
                exchange="NSE",
                side="BUY",
                timeframe="INTRADAY",
                product_hint="MIS",
                trigger_price=Decimal("1850.00"),
                stop_loss=Decimal("1832.00"),
                targets=(("T1", Decimal("1874.00")),),
                provider_note=SAMPLE_NOTE,
                status="expired",
                published_at=now - timedelta(hours=3),
                expires_at=now - timedelta(minutes=10),
                segment="equity",
                channel_code=EQUITY_CHANNEL_CODE,
                horizon_raw="Short term",
            ),
            NormalizedSignal(
                external_ref="mani-sbin-buy",
                symbol="SBIN",
                exchange="NSE",
                side="BUY",
                timeframe="INTRADAY",
                product_hint="CNC",
                trigger_price=Decimal("820.00"),
                stop_loss=Decimal("808.00"),
                targets=(("T1", Decimal("836.00")),),
                provider_note=SAMPLE_NOTE,
                status="withdrawn",
                published_at=now - timedelta(minutes=30),
                expires_at=now + timedelta(minutes=60),
                segment="equity",
                channel_code=EQUITY_CHANNEL_CODE,
                horizon_raw="Long term",
            ),
        ]
