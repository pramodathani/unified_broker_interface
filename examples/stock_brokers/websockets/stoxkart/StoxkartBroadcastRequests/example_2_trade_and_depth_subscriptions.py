"""Builds the trade and depth subscriptions for one Stoxkart instrument and reads their fields back.

A Stoxkart subscription is the 83-byte header followed by the exchange segment (1 byte), -1 (4 bytes), a scrip count of 1 (1 byte), a blank 20-byte watchlist name and the token as 20 bytes, 129 bytes in all. The quote stream sends two per instrument: code 12 for trades and code 23 for depth. `StoxkartBroadcastRequests.subscription` builds either one.

This program builds both for NSE token 2885 (segment 1) and unpacks them with `struct`. It needs no stand-ins.

Notice that the two requests differ only in their first byte.

Run it from the project root:

    python examples/stock_brokers/websockets/stoxkart/StoxkartBroadcastRequests/example_2_trade_and_depth_subscriptions.py
"""

import struct

from stock_brokers.websockets.stoxkart import (
    StoxkartBroadcastRequests,
)


class TradeAndDepthSubscriptionsExample:
    """Builds and reads back two subscriptions.

    Attributes:
        requests (StoxkartBroadcastRequests): The request builder being shown.
    """

    def __init__(self):
        """Builds the request builder.

        Returns:
            None: This method returns nothing.
        """
        self.requests = StoxkartBroadcastRequests()

    def run(self):
        """Prints each subscription's size and fields, and where the two differ.

        Returns:
            None: This method returns nothing.
        """
        trade = self.requests.subscription(12, 1, '2885')
        depth = self.requests.subscription(23, 1, '2885')
        subscriptions = [
            trade,
            depth,
        ]
        for request in subscriptions:
            code, length = struct.unpack_from('<BH', request)
            segment, minus_one, count, watchlist, token = struct.unpack_from('<Bib20s20s', request, 83)
            print(f'{len(request)} bytes: code={code} length={length} segment={segment} {minus_one} count={count} token={token.rstrip(bytes(1))!r}')
        differing = []
        for index in range(len(trade)):
            if trade[index] != depth[index]:
                differing.append(index)
        print(f'Byte positions that differ: {differing}')


if __name__ == '__main__':
    TradeAndDepthSubscriptionsExample().run()
