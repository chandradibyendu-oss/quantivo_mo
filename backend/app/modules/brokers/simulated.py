from app.modules.brokers.adapter import BrokerAdapter, OrderDraft, TradingDisabled

_DISABLED = (
    "The simulated broker does not place, modify, cancel, or fill orders in this build."
)


class SimulatedBrokerAdapter:
    """In-memory skeleton. It has no network client and stores no credentials."""

    code = "simulated"

    def place_order(self, order: OrderDraft) -> str:
        raise TradingDisabled(_DISABLED)

    def modify_order(self, broker_order_id: str, order: OrderDraft) -> None:
        raise TradingDisabled(_DISABLED)

    def cancel_order(self, broker_order_id: str) -> None:
        raise TradingDisabled(_DISABLED)

    def get_order(self, broker_order_id: str) -> dict:
        raise TradingDisabled(_DISABLED)

    def get_trades(self, broker_order_id: str) -> list[dict]:
        return []

    def get_positions(self) -> list[dict]:
        return []

    def get_funds(self) -> dict | None:
        return None


def get_simulated_adapter() -> BrokerAdapter:
    return SimulatedBrokerAdapter()
