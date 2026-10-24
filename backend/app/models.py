"""Import every model so Alembic and metadata see one registry."""

from app.modules.audit.models import AuditEvent
from app.modules.brokers.models import BrokerAccount, BrokerConnection, PositionSnapshot
from app.modules.feeds.models import SourceFeed
from app.modules.identity.models import (
    OtpChallenge,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserSession,
)
from app.modules.notifications.models import Notification
from app.modules.orders.models import BrokerOrder, OrderIntent, TradeExecution
from app.modules.risk.models import RiskProfile
from app.modules.scanners.models import ChannelRegistration, Scanner, ScannerProvider, SourceChannel
from app.modules.signals.models import CallClock, Signal
from app.modules.subscriptions.models import (
    PaymentTransaction,
    ScannerSubscription,
    SubscriptionEntitlement,
)

__all__ = [
    "AuditEvent",
    "ChannelRegistration",
    "BrokerAccount",
    "CallClock",
    "BrokerConnection",
    "BrokerOrder",
    "Notification",
    "OrderIntent",
    "OtpChallenge",
    "PaymentTransaction",
    "Permission",
    "PositionSnapshot",
    "RiskProfile",
    "Role",
    "RolePermission",
    "Scanner",
    "ScannerProvider",
    "SourceChannel",
    "SourceFeed",
    "ScannerSubscription",
    "Signal",
    "SubscriptionEntitlement",
    "TradeExecution",
    "User",
    "UserRole",
    "UserSession",
]
