"""Wisdom Capital's quote subscriptions: XTS's `SEGMENT:INSTRUMENT_ID`, with the segment as its number."""

from stock_brokers.instruments.mapping.utilities.segments import (
    CASH_SEGMENTS,
    INDEX_SEGMENTS,
    split_segment_value,
)
from unified_broker_interface.utilities.quote_subscriptions.base import BrokerQuoteSubscription


class WisdomCapitalQuoteSubscription(BrokerQuoteSubscription):
    """Spells a Wisdom Capital mapping row as `SEGMENT:INSTRUMENT_ID`, such as `2:35000`.

    Attributes:
        SEGMENT_NUMBERS (dict): Each canonical exchange to its XTS segment numbers for cash and indices, currency derivatives, commodity derivatives and other derivatives.
    """

    BROKER_NAME = "wisdom_capital"
    SEGMENT_NUMBERS = {
        "nse": {
            "cash": 1,
            "currency": 3,
            "commodity": 4,
            "derivative": 2,
        },
        "bse": {
            "cash": 11,
            "currency": 13,
            "commodity": None,
            "derivative": 12,
        },
        "mcx": {
            "cash": None,
            "currency": None,
            "commodity": 51,
            "derivative": 51,
        },
        "ncdex": {
            "cash": None,
            "currency": None,
            "commodity": 21,
            "derivative": 21,
        },
    }

    def member(self, identity, broker_token, order_symbol):
        """The XTS segment number and the exchange instrument id.

        Args:
            identity (dict): The unified instrument's row.
            broker_token (str): XTS's exchange instrument id.
            order_symbol (str | None): Unused.

        Returns:
            str | None: The member, or None when XTS has no segment for the instrument.
        """
        del order_symbol
        exchange, bare = split_segment_value(identity["segment"])
        numbers = self.SEGMENT_NUMBERS.get(exchange)
        if numbers is None:
            return None
        if bare in CASH_SEGMENTS or bare in INDEX_SEGMENTS:
            number = numbers["cash"]
        elif bare.startswith("currenc"):
            number = numbers["currency"]
        elif bare.startswith("commodit"):
            number = numbers["commodity"]
        else:
            number = numbers["derivative"]
        if number is None:
            return None
        return f"{number}:{broker_token}"
