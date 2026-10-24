"""Broker adapter contract.

Concrete adapters must use the broker's own authentication flow. They must not accept
or persist a broker password. Mutating calls stay unimplemented until that adapter has
been reviewed and live trading is explicitly enabled in a future build.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


class TradingDisabled(Exception):
    """The adapter refused to send an order."""


@dataclass(frozen=True)
class OrderDraft:
    symbol: str
    exchange: str
    side: str
    product: str
    quantity: int
    price: Decimal
    idempotency_key: str


class BrokerAdapter(Protocol):
    code: str

    def place_order(self, order: OrderDraft) -> str:
        """Return the broker order id. Must not imply that the order has filled."""

    def modify_order(self, broker_order_id: str, order: OrderDraft) -> None:
        ...

    def cancel_order(self, broker_order_id: str) -> None:
        ...

    def get_order(self, broker_order_id: str) -> dict:
        ...

    def get_trades(self, broker_order_id: str) -> list[dict]:
        ...

    def get_positions(self) -> list[dict]:
        ...

    def get_funds(self) -> dict | None:
        ...
