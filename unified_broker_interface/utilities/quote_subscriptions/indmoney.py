"""INDmoney's quote subscriptions: `SEGMENT:TOKEN`, with the feed segment INDmoney's REST quotes name."""

from unified_broker_interface.utilities.broker_quotes.indmoney import indmoney_codes
from unified_broker_interface.utilities.quote_subscriptions.base import BrokerQuoteSubscription


class IndmoneyQuoteSubscription(BrokerQuoteSubscription):
    """Spells an INDmoney mapping row as `SEGMENT:TOKEN`, such as `NFO:35000`."""

    BROKER_NAME = "indmoney"

    def member(self, identity, broker_token, order_symbol):
        """The INDstocks feed segment and the token.

        Args:
            identity (dict): The unified instrument's row.
            broker_token (str): INDmoney's token.
            order_symbol (str | None): Unused.

        Returns:
            str | None: The member, or None for a segment whose INDstocks quotes are not trusted.
        """
        del order_symbol
        codes = indmoney_codes(identity)
        if codes is None:
            return None
        feed_segment = codes[0]
        return f"{feed_segment}:{broker_token}"
