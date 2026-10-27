"""The quote subscription spellings, one per broker the allocation can give instruments to."""

from unified_broker_interface.utilities.quote_subscriptions.dhan import (
    DhanQuoteSubscription,
)
from unified_broker_interface.utilities.quote_subscriptions.flattrade import (
    FlattradeQuoteSubscription,
)
from unified_broker_interface.utilities.quote_subscriptions.fyers import (
    FyersQuoteSubscription,
)
from unified_broker_interface.utilities.quote_subscriptions.indmoney import (
    IndmoneyQuoteSubscription,
)
from unified_broker_interface.utilities.quote_subscriptions.kotak import (
    KotakQuoteSubscription,
)
from unified_broker_interface.utilities.quote_subscriptions.shoonya import (
    ShoonyaQuoteSubscription,
)
from unified_broker_interface.utilities.quote_subscriptions.stoxkart import (
    StoxkartQuoteSubscription,
)
from unified_broker_interface.utilities.quote_subscriptions.wisdom_capital import (
    WisdomCapitalQuoteSubscription,
)
from unified_broker_interface.utilities.quote_subscriptions.zerodha import (
    ZerodhaQuoteSubscription,
)

QUOTE_SUBSCRIPTION_CLASSES = [
    DhanQuoteSubscription,
    FlattradeQuoteSubscription,
    FyersQuoteSubscription,
    IndmoneyQuoteSubscription,
    KotakQuoteSubscription,
    ShoonyaQuoteSubscription,
    StoxkartQuoteSubscription,
    WisdomCapitalQuoteSubscription,
    ZerodhaQuoteSubscription,
]
