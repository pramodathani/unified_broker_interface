"""Builds the connection header a Stoxkart broadcast stream sends first, and reads its fields back.

Every request to Stoxkart's broadcast websocket starts with an 83-byte header, little endian: a request code (1 byte), the whole request's length (2 bytes), a 30-byte client name and a 50-byte token. `StoxkartBroadcastRequests.connection_header` builds the request that opens a session, code 10, whose token is left blank exactly as Stoxkart's website sends it, because the feed takes no login.

This program builds the header and unpacks it with `struct`. It needs no stand-ins.

Notice that the length field says 83, the client name is padded with zero bytes, and the token is empty.

Run it from the project root:

    python examples/stock_brokers/websockets/stoxkart/StoxkartBroadcastRequests/example_1_connection_header.py
"""

import struct

from stock_brokers.websockets.stoxkart import (
    StoxkartBroadcastRequests,
)


class ConnectionHeaderExample:
    """Builds and reads back the connection header.

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
        """Prints the header's size and fields.

        Returns:
            None: This method returns nothing.
        """
        header = self.requests.connection_header()
        code, length, client_name, token = struct.unpack('<BH30s50s', header)
        print(f'{len(header)} bytes: code={code} length={length}')
        print(f"client name={client_name.rstrip(bytes(1))!r} token={token.rstrip(bytes(1))!r}")


if __name__ == '__main__':
    ConnectionHeaderExample().run()
