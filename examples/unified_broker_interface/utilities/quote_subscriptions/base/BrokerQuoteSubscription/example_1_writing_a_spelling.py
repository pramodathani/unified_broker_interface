"""Writes the quote subscription spelling for a made-up broker and spells two instruments with it.

A broker's spelling subclasses `BrokerQuoteSubscription`, sets `BROKER_NAME` and implements `member`, which turns a mapping row into the string the broker's quote websocket subscribes, or None when the feed cannot stream the instrument. This made-up broker writes `EXCHANGE/TOKEN` and streams only NSE.

The spelling reads nothing, so it is built with no Redis client. It needs no data store, no network and no broker login.

Notice that the BSE instrument is answered None, which is how the allocation learns that this broker cannot carry it.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/base/BrokerQuoteSubscription/example_1_writing_a_spelling.py
"""

from unified_broker_interface.utilities.quote_subscriptions.base import (
    BrokerQuoteSubscription,
)


class SlashQuoteSubscription(BrokerQuoteSubscription):
    """Spells a made-up broker's mapping rows as `EXCHANGE/TOKEN`, on NSE only."""

    BROKER_NAME = 'slash_broker'

    def member(self, identity, broker_token, order_symbol):
        """The exchange in capitals, a slash and the token, or None off NSE.

        Args:
            identity (dict): The unified instrument's row.
            broker_token (str): The broker's token.
            order_symbol (str | None): Unused.

        Returns:
            str | None: The member, or None when the instrument is not on NSE.
        """
        del order_symbol
        if identity['exchange'] != 'nse':
            return None
        return f"{identity['exchange'].upper()}/{broker_token}"


class WritingASpellingExample:
    """Spells an NSE and a BSE instrument with the made-up broker's spelling.

    Attributes:
        spelling (SlashQuoteSubscription): The spelling being shown.
    """

    def __init__(self):
        """Builds the spelling with no Redis client.

        Returns:
            None: This method returns nothing.
        """
        self.spelling = SlashQuoteSubscription(None)

    def run(self):
        """Prints the broker's name and both members.

        Returns:
            None: This method returns nothing.
        """
        print(f'Broker: {SlashQuoteSubscription.BROKER_NAME}')
        nse = {
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
        }
        bse = {
            'exchange': 'bse',
            'segment': 'bse_equities',
            'shape': 'security',
        }
        print(f"NSE RELIANCE: {self.spelling.member(nse, '2885', None)}")
        print(f"BSE RELIANCE: {self.spelling.member(bse, '500325', None)}")


if __name__ == '__main__':
    WritingASpellingExample().run()
