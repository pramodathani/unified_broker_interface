"""Kotak's quote subscriptions: `exchange_segment|token`, with the segment Kotak's REST quotes use."""

from unified_broker_interface.utilities.broker_quotes.kotak import kotak_segment
from unified_broker_interface.utilities.quote_subscriptions.base import BrokerQuoteSubscription


class KotakQuoteSubscription(BrokerQuoteSubscription):
    """Spells a Kotak mapping row as `exchange_segment|token`, such as `nse_fo|35000`."""

    BROKER_NAME = "kotak"

    def member(self, identity, broker_token, order_symbol):
        """The Kotak exchange segment and the token.

        Args:
            identity (dict): The unified instrument's row.
            broker_token (str): Kotak's token.
            order_symbol (str | None): Unused.

        Returns:
            str | None: The member, or None when Kotak has no segment for the instrument.
        """
        del order_symbol
        segment = kotak_segment(identity)
        if segment is None:
            return None
        return f"{segment}|{broker_token}"
