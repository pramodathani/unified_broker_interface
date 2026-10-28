"""Shoonya's quote subscriptions: Noren's `EXCHANGE|TOKEN`."""

from unified_broker_interface.utilities.broker_quotes.utilities.noren import noren_exchange
from unified_broker_interface.utilities.quote_subscriptions.base import BrokerQuoteSubscription


class ShoonyaQuoteSubscription(BrokerQuoteSubscription):
    """Spells a Shoonya mapping row as `EXCHANGE|TOKEN`, such as `NFO|35000`."""

    BROKER_NAME = "shoonya"

    def member(self, identity, broker_token, order_symbol):
        """The Noren exchange and the token.

        Args:
            identity (dict): The unified instrument's row.
            broker_token (str): Shoonya's token.
            order_symbol (str | None): Unused.

        Returns:
            str | None: The member, or None when Noren has no exchange for the instrument.
        """
        del order_symbol
        exchange = noren_exchange(identity)
        if exchange is None:
            return None
        return f"{exchange}|{broker_token}"
