"""Zerodha's quote subscriptions: the bare Kite instrument token, which carries its own segment."""

from unified_broker_interface.utilities.quote_subscriptions.base import BrokerQuoteSubscription


class ZerodhaQuoteSubscription(BrokerQuoteSubscription):
    """Spells a Zerodha mapping row as a Kite instrument token."""

    BROKER_NAME = "zerodha"

    def member(self, identity, broker_token, order_symbol):
        """The Kite instrument token, which Kite streams for every segment it lists.

        Args:
            identity (dict): The unified instrument's row.
            broker_token (str): The Kite instrument token.
            order_symbol (str | None): Unused.

        Returns:
            str | None: The token, or None when it is not a number.
        """
        del identity, order_symbol
        token = str(broker_token).strip()
        if not token.isdigit():
            return None
        return token
