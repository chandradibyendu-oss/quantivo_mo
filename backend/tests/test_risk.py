from decimal import Decimal

from app.modules.risk.calculator import RiskInputs, calculate


def _inputs(**overrides) -> RiskInputs:
    values = dict(
        side="BUY",
        trigger_price=Decimal("2450.00"),
        stop_loss=Decimal("2432.00"),
        lot_size=1,
        max_risk_inr=Decimal("500.00"),
        max_quantity=500,
        max_exposure_inr=Decimal("200000.00"),
        capital_allocation_inr=Decimal("50000.00"),
    )
    values.update(overrides)
    return RiskInputs(**values)


def test_quantity_uses_risk_not_capital_allocation():
    base = calculate(_inputs())
    larger_capital = calculate(_inputs(capital_allocation_inr=Decimal("1000000.00")))
    assert base.ok is True
    assert base.quantity == 27
    assert base.quantity == larger_capital.quantity
    assert base.risk_amount == Decimal("486.00")


def test_quantity_floors_and_respects_lot_size():
    result = calculate(_inputs(max_risk_inr=Decimal("500"), lot_size=5))
    assert result.quantity == 25


def test_exposure_cap_reduces_quantity():
    result = calculate(_inputs(trigger_price=Decimal("1000"), stop_loss=Decimal("990"), max_exposure_inr=Decimal("15000")))
    assert result.ok is True
    assert result.quantity == 15


def test_buy_stop_on_the_wrong_side_is_rejected():
    result = calculate(_inputs(stop_loss=Decimal("2460")))
    assert result.ok is False
    assert result.quantity is None


def test_sell_distance_and_wrong_side():
    valid = calculate(
        _inputs(side="SELL", trigger_price=Decimal("4100"), stop_loss=Decimal("4145"), max_exposure_inr=None)
    )
    invalid = calculate(_inputs(side="SELL", trigger_price=Decimal("4100"), stop_loss=Decimal("4000")))
    assert valid.quantity == 11
    assert invalid.ok is False


def test_risk_too_small_for_one_share():
    result = calculate(_inputs(max_risk_inr=Decimal("10"), max_quantity=None, max_exposure_inr=None))
    assert result.ok is False
    assert "18.00" in (result.reason or "")


def test_one_contract_lot_over_max_risk_has_no_quantity():
    result = calculate(
        _inputs(
            trigger_price=Decimal("180"),
            stop_loss=Decimal("150"),
            lot_size=25,
            max_quantity=None,
            max_exposure_inr=None,
        )
    )
    assert result.ok is False
    assert result.quantity == 0
    assert "750.00" in (result.reason or "")
