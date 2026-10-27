"""Quantity model.

Quantity = floor(maximum rupee risk / per-share risk), then rounded down to the lot size
and reduced to satisfy the optional quantity cap and exposure cap.

Capital allocation is the cash set aside for the trade. It is not the amount the user
is willing to lose, and it is not an input to the division above.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

FORMULA = (
    "Suggested quantity = floor(maximum rupee risk / per-share risk), then rounded down to the "
    "lot size and capped by the quantity and exposure limits. Capital allocation is cash set "
    "aside for the trade, not the amount at risk."
)
FUNDS_NOTE = (
    "Another whole number of lots can be entered while the call can be confirmed. When Zerodha "
    "is signed in, the quantity is kept only if Zerodha shows enough margin. This build still "
    "does not send the order."
)


@dataclass(frozen=True)
class RiskInputs:
    side: str
    trigger_price: Decimal
    stop_loss: Decimal
    lot_size: int
    max_risk_inr: Decimal
    max_quantity: int | None
    max_exposure_inr: Decimal | None
    capital_allocation_inr: Decimal


@dataclass(frozen=True)
class RiskResult:
    ok: bool
    reason: str | None
    per_share_risk: Decimal | None
    quantity: int | None
    risk_amount: Decimal | None
    notional: Decimal | None


def _floor_to_lot(quantity: int, lot_size: int) -> int:
    if quantity < lot_size:
        return 0
    return quantity - (quantity % lot_size)


def quantity_refusal(requested: int, lot_size: int) -> str | None:
    """Refuse a quantity that is not a whole number of lots."""

    if lot_size < 1 or requested < lot_size or requested % lot_size != 0:
        return f"Quantity must be a whole number of lots of {lot_size}."
    return None


def calculate(inputs: RiskInputs) -> RiskResult:
    if inputs.trigger_price <= 0 or inputs.stop_loss <= 0:
        return RiskResult(False, "Prices must be positive.", None, None, None, None)
    if inputs.lot_size < 1:
        return RiskResult(False, "Lot size is invalid.", None, None, None, None)
    if inputs.side == "BUY" and inputs.stop_loss >= inputs.trigger_price:
        return RiskResult(
            False, "For a buy, the stop-loss must be below the trigger.", None, None, None, None
        )
    if inputs.side == "SELL" and inputs.stop_loss <= inputs.trigger_price:
        return RiskResult(
            False, "For a sell, the stop-loss must be above the trigger.", None, None, None, None
        )
    if inputs.side not in {"BUY", "SELL"}:
        return RiskResult(False, "Signal side is not supported.", None, None, None, None)

    per_share = abs(inputs.trigger_price - inputs.stop_loss)
    if per_share <= 0:
        return RiskResult(False, "Per-share risk must be greater than zero.", None, None, None, None)

    raw = int((inputs.max_risk_inr / per_share).to_integral_value(rounding=ROUND_FLOOR))
    quantity = _floor_to_lot(raw, inputs.lot_size)
    if inputs.max_quantity is not None:
        quantity = min(quantity, _floor_to_lot(inputs.max_quantity, inputs.lot_size))
    if inputs.max_exposure_inr is not None:
        exposure_qty = int(
            (inputs.max_exposure_inr / inputs.trigger_price).to_integral_value(rounding=ROUND_FLOOR)
        )
        quantity = min(quantity, _floor_to_lot(exposure_qty, inputs.lot_size))
    if quantity < inputs.lot_size:
        lot_loss = (per_share * inputs.lot_size).quantize(Decimal("0.01"))
        if raw < inputs.lot_size:
            reason = (
                f"One lot would lose ₹{format(lot_loss, 'f')}, which is more than the maximum risk."
            )
        else:
            reason = "Risk limits do not allow the minimum tradable quantity."
        return RiskResult(False, reason, per_share, 0, None, None)
    return RiskResult(
        True,
        None,
        per_share,
        quantity,
        per_share * quantity,
        inputs.trigger_price * quantity,
    )
