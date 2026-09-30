"""Builds the connection request and the scrip and depth subscriptions a Kotak quotes socket sends.

`KotakFeedRequests` builds the binary requests a client sends to Kotak's HSM feed. Each is a frame: its length in two bytes, a type byte, a field count, and fields of an id, a two-byte length and the value. `connection` (type 1) carries the access token, the session id and the source `JS_API`, and `subscription` (type 4) lists up to 100 topic names, `sf|...` for scrip or `dp|...` for depth, on channel 1.

This program builds the connection request and both subscriptions for two instruments, prints them as hex, and reads the topic names back out of the scrip subscription with `KotakFrameReader`. It needs no stand-ins.

Notice that each instrument becomes the topic `sf|nse_cm|2885` or `sf|nse_cm|1594` in the scrip subscription.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakFeedRequests/example_1_connection_and_subscription.py
"""


from stock_brokers.websockets.kotak import (
    KotakFeedRequests,
    KotakFrameReader,
)


class ConnectionAndSubscriptionExample:
    """Builds and reads back Kotak feed requests.

    Attributes:
        requests (KotakFeedRequests): The request builder being shown.
        instrument_tokens (list): The instruments to subscribe.
    """

    def __init__(self):
        """Builds the request builder and the instruments.

        Returns:
            None: This method returns nothing.
        """
        self.requests = KotakFeedRequests()
        self.instrument_tokens = [
            'nse_cm|2885',
            'nse_cm|1594',
        ]

    def run(self):
        """Prints each request and the topic names inside the scrip subscription.

        Returns:
            None: This method returns nothing.
        """
        print(f"Connection: {self.requests.connection('kotak-token-1', 'kotak-sid-1').hex()}")
        scrip = self.requests.subscription('sf', self.instrument_tokens)
        print(f'Scrip subscription: {scrip.hex()}')
        print(f"Depth subscription: {self.requests.subscription('dp', self.instrument_tokens).hex()}")
        reader = KotakFrameReader(scrip)
        reader.read_unsigned(2)
        print(f'Frame type {reader.read_unsigned(1)} with {reader.read_unsigned(1)} fields')
        reader.read_unsigned(1)
        reader.read_unsigned(2)
        for _ in range(reader.read_unsigned(2)):
            print(f'  topic {reader.read_text(reader.read_unsigned(1))}')


if __name__ == '__main__':
    ConnectionAndSubscriptionExample().run()
