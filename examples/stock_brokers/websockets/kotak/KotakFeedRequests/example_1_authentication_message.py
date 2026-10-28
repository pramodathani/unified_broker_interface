"""Builds the authentication message a Kotak quotes socket sends as soon as its SFeed connection opens.

`KotakFeedRequests.authentication` builds the `native_batch` authentication message as a JSON text frame, the same message Kotak's own Python SDK, `kotakneoapi` 3.0.9, sends. The account's unique client code goes in `user`, the session id from Kotak's login goes in `auth`, and the moment of the request goes in `conn_req_time` in Unix milliseconds. Every other field is fixed: the `native_batch` format that makes Kotak send little-endian binary market pictures, the source, platform and SDK version, and `sessionValidation` set to false.

This program builds the message for a made-up client code and session id at 09:15 IST on 2026-10-28, prints the text exactly as the socket would send it, and then prints its fields one per line. It needs no stand-ins.

Notice that the message is ordinary JSON, not a binary frame as on the retired HSM feed, and that it carries the session id but no access token.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakFeedRequests/example_1_authentication_message.py
"""

import datetime
import json
import zoneinfo

from stock_brokers.websockets.kotak import (
    KotakFeedRequests,
)

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class AuthenticationMessageExample:
    """Builds and reads back the Kotak feed's authentication message.

    Attributes:
        requests (KotakFeedRequests): The request builder being shown.
        requested_at_milliseconds (int): The fixed moment of the request, in Unix milliseconds.
    """

    def __init__(self):
        """Builds the request builder and the fixed request time.

        Returns:
            None: This method returns nothing.
        """
        self.requests = KotakFeedRequests()
        requested_at = datetime.datetime(2026, 10, 28, 9, 15, tzinfo=INDIA)
        self.requested_at_milliseconds = int(requested_at.timestamp() * 1000)

    def run(self):
        """Prints the authentication message and each of its fields.

        Returns:
            None: This method returns nothing.
        """
        message = self.requests.authentication('ABCD1', 'kotak-sid-1', self.requested_at_milliseconds)
        print(f'Sent as text: {message}')
        print('Fields:')
        for name, value in json.loads(message).items():
            print(f'  {name}: {value!r}')


if __name__ == '__main__':
    AuthenticationMessageExample().run()
