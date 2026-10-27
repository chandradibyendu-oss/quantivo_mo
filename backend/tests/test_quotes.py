from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.modules.quotes.fyers import QuotePrint, fyers_code, parse_fyers_quotes, read_last_prices
from app.modules.signals.schemas import ProviderValues, QuantivoValues, SignalCard
from app.modules.signals.views import _with_quotes


def test_an_nse_cash_symbol_becomes_a_fyers_code():
    series = {"SBIN": "EQ", "RENUKA": "BE"}
    assert fyers_code("NSE", "sbin", series) == "NSE:SBIN-EQ"
    assert fyers_code("NSE", "RENUKA", series) == "NSE:RENUKA-BE"
    assert fyers_code("NSE", "M&M", series) == "NSE:M&M-EQ"
    assert fyers_code("NSE", "NIFTY 24500 CE", series) is None
    assert fyers_code("NFO", "NIFTY", series) is None


def test_a_quote_payload_keeps_only_a_positive_last_price():
    body = """
    {"s":"ok","d":[
      {"n":"NSE:SBIN-EQ","s":"ok","v":{"lp":785.5}},
      {"n":"NSE:IDEA-EQ","s":"error","v":{}},
      {"n":"NSE:ZERO-EQ","s":"ok","v":{"lp":0}}
    ]}
    """
    parsed = parse_fyers_quotes(body)
    assert parsed == {"NSE:SBIN-EQ": QuotePrint(Decimal("785.5"))}
    assert parse_fyers_quotes('{"s":"error"}') is None


def test_the_percent_comes_from_the_previous_close():
    quoted = parse_fyers_quotes(
        '{"s":"ok","d":[{"n":"NSE:SBIN-EQ","s":"ok","v":{"lp":785.5,"chp":1.25}}]}'
    )
    assert quoted is not None
    assert quoted["NSE:SBIN-EQ"].change_percent == Decimal("1.25")
    computed = parse_fyers_quotes(
        '{"s":"ok","d":[{"n":"NSE:SBIN-EQ","s":"ok","v":{"lp":"99","prev_close_price":"100"}}]}'
    )
    assert computed is not None
    assert computed["NSE:SBIN-EQ"].change_percent == Decimal("-1.00")
    flat = parse_fyers_quotes(
        '{"s":"ok","d":[{"n":"NSE:SBIN-EQ","s":"ok","v":{"lp":100,"prev_close_price":0}}]}'
    )
    assert flat is not None
    assert flat["NSE:SBIN-EQ"].change_percent is None


def test_a_rate_limit_pauses_the_next_read():
    from app.modules.quotes.budget import set_pause_jitter
    from app.modules.quotes.fyers import clear_quote_cache, pause_quotes

    now = datetime(2026, 10, 24, 6, 0, tzinfo=UTC)
    set_pause_jitter(lambda: 0)

    def opener(url, authorization):
        raise AssertionError(url + authorization)

    pause_quotes(now)
    try:
        paused = read_last_prices(
            [("NSE", "SBIN")],
            app_id="app",
            access_token="token",
            opener=opener,
            cache={},
            series={"SBIN": "EQ"},
            now=now + timedelta(seconds=5),
        )
        assert paused.source == "unavailable"
        assert paused.prices == {}
    finally:
        clear_quote_cache()
        set_pause_jitter(lambda: __import__("random").uniform(0, 5))


def test_quotes_stay_empty_until_a_fyers_app_is_configured():
    def opener(url, authorization):
        raise AssertionError(url + authorization)

    batch = read_last_prices(
        [("NSE", "SBIN")],
        app_id="",
        access_token="",
        opener=opener,
        cache={},
        series={"SBIN": "EQ"},
    )
    assert batch.source == "unconfigured"
    assert batch.prices == {}


def test_a_read_is_reused_for_a_minute_and_a_failure_returns_no_price():
    calls = {"n": 0}
    now = datetime(2026, 10, 23, 4, 30, tzinfo=UTC)

    def opener(url, authorization):
        calls["n"] += 1
        assert authorization == "app:token"
        assert "NSE:SBIN-EQ" in url
        if calls["n"] == 1:
            assert "NSE:M%26M-EQ" in url
        return '{"s":"ok","d":[{"n":"NSE:SBIN-EQ","s":"ok","v":{"lp":785.5}}]}'

    kwargs = {
        "app_id": "app",
        "access_token": "token",
        "opener": opener,
        "cache": {},
        "series": {"SBIN": "EQ"},
    }
    symbols = [("NSE", "SBIN"), ("NSE", "M&M")]
    first = read_last_prices(symbols, now=now, **kwargs)
    second = read_last_prices(symbols, now=now + timedelta(seconds=10), **kwargs)
    assert first.source == "fyers"
    assert first.prices[("NSE", "SBIN")] == Decimal("785.5")
    assert ("NSE", "M&M") not in first.prices
    assert second.prices == first.prices
    assert calls["n"] == 1

    still = read_last_prices([("NSE", "SBIN")], now=now + timedelta(seconds=16), **kwargs)
    assert still.prices == first.prices
    assert calls["n"] == 1

    later = read_last_prices([("NSE", "SBIN")], now=now + timedelta(seconds=61), **kwargs)
    assert later.source == "fyers"
    assert calls["n"] == 2

    def fail(url, authorization):
        raise OSError("down")

    failed = read_last_prices(
        [("NSE", "LT")],
        app_id="app",
        access_token="token",
        opener=fail,
        cache={},
        series={},
        now=now,
    )
    assert failed.source == "unavailable"
    assert failed.prices == {}


def test_a_fresh_socket_price_is_not_read_again_from_the_quote_call():
    from app.modules.quotes.fyers import clear_quote_cache, remember_quote
    from app.modules.quotes.live import clear_live, remember_tick

    now = datetime(2026, 10, 23, 4, 30, tzinfo=UTC)
    remember_quote("NSE:SBIN-EQ", Decimal("780"), now)
    remember_tick(
        {
            "symbol": "NSE:SBIN-EQ",
            "type": "sf",
            "ltp": 785.5,
            "prev_close_price": "775.80",
        },
        now,
    )

    def opener(url, authorization):
        raise AssertionError(url + authorization)

    try:
        batch = read_last_prices(
            [("NSE", "SBIN")],
            app_id="app",
            access_token="token",
            opener=opener,
            cache={},
            series={"SBIN": "EQ"},
            now=now + timedelta(seconds=10),
        )
    finally:
        clear_live()
        clear_quote_cache()
    assert batch.source == "fyers"
    assert batch.prices[("NSE", "SBIN")] == Decimal("785.5")
    assert batch.changes[("NSE", "SBIN")] == Decimal("1.25")


def test_a_socket_price_far_from_the_quote_is_ignored():
    from app.modules.quotes.fyers import clear_quote_cache, remember_quote
    from app.modules.quotes.live import clear_live, fresh_ticks, remember_tick

    now = datetime(2026, 10, 27, 9, 20, tzinfo=UTC)
    code = "NSE:COHANCE-EQ"
    wild = {"symbol": code, "type": "sf", "ltp": "1605.10", "prev_close_price": "1580"}
    kept = {"symbol": code, "type": "sf", "ltp": "470.10", "prev_close_price": "463.55"}
    try:
        remember_tick(kept, now)
        assert fresh_ticks({code}, now) == {}
        remember_quote(code, Decimal("470.10"), now)
        remember_tick(wild, now)
        assert fresh_ticks({code}, now) == {}
        remember_tick(kept, now)
        assert fresh_ticks({code}, now)[code].price == Decimal("470.10")
        assert fresh_ticks({code}, now)[code].change_percent == Decimal("1.41")
        remember_tick(wild, now + timedelta(seconds=1))
        assert fresh_ticks({code}, now + timedelta(seconds=1))[code].price == Decimal("470.10")
    finally:
        clear_live()
        clear_quote_cache()


def test_the_call_carries_the_last_price_and_leaves_quantity_alone(monkeypatch):
    def fake(pairs):
        assert pairs == [("NSE", "SBIN")]
        from app.modules.quotes.fyers import QuoteBatch

        return QuoteBatch(
            "fyers",
            {("NSE", "SBIN"): Decimal("785.5")},
            {("NSE", "SBIN"): Decimal("1.25")},
        )

    monkeypatch.setattr("app.modules.signals.views.read_last_prices", fake)
    card = SignalCard(
        id=uuid4(),
        symbol="SBIN",
        exchange="NSE",
        side="BUY",
        timeframe="INTRADAY",
        product_hint="MIS",
        status="active",
        stored_status="active",
        warning=None,
        executable=True,
        guide="waiting",
        guide_label="Waiting",
        guide_hint="The entry window is still open.",
        published_at=datetime(2026, 10, 23, 4, 30, tzinfo=UTC),
        expires_at=datetime(2026, 10, 23, 10, 0, tzinfo=UTC),
        provider_name="Mani's",
        scanner_id=uuid4(),
        scanner_name="Mani's Channel",
        segment="equity",
        channel_code="equity",
        channel_name="Equity",
        horizon_raw="Intraday",
        lot_size=1,
        provider_values=ProviderValues(
            trigger_price="820.00",
            stop_loss="808.00",
            targets=[],
            note=None,
        ),
        quantivo_values=QuantivoValues(
            suggested_quantity=12,
            per_share_risk="12.00",
            estimated_risk_inr="144.00",
            notional_inr="9840.00",
            capital_allocation_inr="50000.00",
            max_risk_inr="500.00",
            formula="floor(max risk / abs(trigger - stop))",
            funds_check="Funds were not checked.",
            unavailable_reason=None,
        ),
        suggested_quantity=12,
    )
    closed = card.model_copy(update={"status": "expired", "symbol": "INFY", "guide": "expired"})
    source, quoted = _with_quotes([card, closed])
    assert source == "fyers"
    assert quoted[0].last_price == "785.50"
    assert quoted[0].change_percent == "1.25"
    assert quoted[0].quote_state == "ready"
    assert quoted[0].suggested_quantity == 12
    assert quoted[0].provider_values.trigger_price == "820.00"
    assert quoted[1].last_price is None
    assert quoted[1].quote_state == "unconfigured"
