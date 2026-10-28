"""Dhan's quote subscriptions: `SEGMENT:SECURITY_ID`, with the segment Dhan's REST quotes use."""

from unified_broker_interface.utilities.broker_quotes.dhan import dhan_segment
from unified_broker_interface.utilities.quote_subscriptions.base import BrokerQuoteSubscription


class DhanQuoteSubscription(BrokerQuoteSubscription):
    """Spells a Dhan mapping row as `SEGMENT:SECURITY_ID`, such as `NSE_FNO:35000`."""

    BROKER_NAME = "dhan"

    def member(self, identity, broker_token, order_symbol):
        """The Dhan segment and the security id.

        Args:
            identity (dict): The unified instrument's row.
            broker_token (str): Dhan's security id.
            order_symbol (str | None): Unused.

        Returns:
            str | None: The member, or None when Dhan has no segment for the instrument.
        """
        del order_symbol
        segment = dhan_segment(identity)
        if segment is None:
            return None
        return f"{segment}:{broker_token}"
