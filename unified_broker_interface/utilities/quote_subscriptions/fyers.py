"""Fyers' quote subscriptions: the Fyers symbol, which the mapping keeps as the order symbol."""

from unified_broker_interface.utilities.quote_subscriptions.base import BrokerQuoteSubscription


class FyersQuoteSubscription(BrokerQuoteSubscription):
    """Spells a Fyers mapping row as its Fyers symbol, such as `NSE:SBIN-EQ`."""

    BROKER_NAME = "fyers"

    def member(self, identity, broker_token, order_symbol):
        """The Fyers symbol, except for currency derivatives, whose ticks the Fyers normalizer does not read.

        Args:
            identity (dict): The unified instrument's row.
            broker_token (str): Unused, because Fyers subscribes by symbol.
            order_symbol (str | None): The Fyers symbol.

        Returns:
            str | None: The symbol, or None when the mapping has none or the instrument is a currency derivative.
        """
        del broker_token
        symbol = str(order_symbol or "").strip()
        if ":" not in symbol:
            return None
        if "_currenc" in str(identity.get("segment") or ""):
            return None
        return symbol
