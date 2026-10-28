"""Builds the one subscription message that asks Kotak's SFeed for several instruments' five-level depth.

`KotakFeedRequests.subscription` builds a JSON text frame with the event `subscribeDepth`, which makes Kotak send each instrument's market picture with five order book rows a side. Every instrument is named as `EXCHANGE|TOKEN`, and all of them go in one comma-separated `inputtoken`, so a whole batch is subscribed with a single message rather than one message per instrument or per topic. `ack_symbol` set to true asks Kotak to answer with message code 1109 and each instrument's trading symbol, which is how the quotes socket names instruments it has no name for.

This program subscribes three instruments from three exchanges: RELIANCE on NSE (`nse_cm|2885`), a NIFTY future (`nse_fo|35003`) and a CRUDEOIL future on MCX (`mcx_fo|440001`). It prints the message as the socket would send it, and then splits `inputtoken` back into its instruments. It needs no stand-ins.

Notice that the exchange names are Kotak's own lower-case segment names, and that the order of the instruments is kept.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakFeedRequests/example_2_subscribing_several_instruments.py
"""

import json

from stock_brokers.websockets.kotak import (
    KotakFeedRequests,
)


class SubscribingSeveralInstrumentsExample:
    """Builds and reads back one Kotak depth subscription for several instruments.

    Attributes:
        requests (KotakFeedRequests): The request builder being shown.
        instrument_tokens (list): The instruments to subscribe, as `EXCHANGE|TOKEN`.
    """

    def __init__(self):
        """Builds the request builder and the instruments.

        Returns:
            None: This method returns nothing.
        """
        self.requests = KotakFeedRequests()
        self.instrument_tokens = [
            'nse_cm|2885',
            'nse_fo|35003',
            'mcx_fo|440001',
        ]

    def run(self):
        """Prints the subscription message and the instruments inside it.

        Returns:
            None: This method returns nothing.
        """
        message = self.requests.subscription(self.instrument_tokens)
        print(f'Sent as text: {message}')
        fields = json.loads(message)
        print(f"Event {fields['event']!r}, asking for trading symbols: {fields['ack_symbol']}")
        for instrument_token in fields['inputtoken'].split(','):
            exchange, _, token = instrument_token.partition('|')
            print(f'  exchange {exchange}, token {token}')


if __name__ == '__main__':
    SubscribingSeveralInstrumentsExample().run()
