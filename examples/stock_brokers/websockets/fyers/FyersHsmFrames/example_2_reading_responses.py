"""Reads Fyers HSM authentication responses and picks the price scale and field table a data packet is read with.

When the feed answers the authentication frame, `auth_response` reads whether it accepted the hsm key (a `K` in the first field) and how many data messages the socket must acknowledge at a time. Data packets carry scaled integer prices: `price_divisor` gives 10 to the precision times the multiplier from the instrument's snapshot, or 100 before any snapshot has said. A packet's values are positional, and `fields_for` picks the table they are read against from the topic name and the number of values: depth topics start `dp`, index topics start `if`, three values or fewer are a lite packet, and anything else is a full data packet.

This program builds an accepted and a refused authentication response byte by byte, reads a truncated one, and asks for divisors and field tables. It needs no stand-ins, because the class only packs and unpacks bytes.

Notice that a truncated response reads as refused with a count of zero rather than raising.

Run it from the project root:

    python examples/stock_brokers/websockets/fyers/FyersHsmFrames/example_2_reading_responses.py
"""

import struct

from stock_brokers.websockets.fyers import (
    FyersHsmFrames,
)


class ReadingResponsesExample:
    """Reads authentication responses and picks price scales and field tables.

    Attributes:
        frames (FyersHsmFrames): The frame reader being shown.
    """

    def __init__(self):
        """Builds the frame reader.

        Returns:
            None: This method returns nothing.
        """
        self.frames = FyersHsmFrames()

    def auth_response(self, status, ack_count):
        """An authentication response as the feed sends it.

        Args:
            status (bytes): `K` for accepted, anything else for refused.
            ack_count (int): How many data messages to acknowledge at a time.

        Returns:
            bytes: The frame.
        """
        return struct.pack('!HBBBH', 0, 1, 2, 1, len(status)) + status + bytes([2]) + struct.pack('!H', 4) + struct.pack('>I', ack_count)

    def run(self):
        """Prints what each response, state and topic reads as.

        Returns:
            None: This method returns nothing.
        """
        print(f"Accepted response: {self.frames.auth_response(self.auth_response(b'K', 50))}")
        print(f"Refused response: {self.frames.auth_response(self.auth_response(b'N', 0))}")
        print(f"Truncated response: {self.frames.auth_response(bytes([0, 0, 1, 2, 1, 0]))}")
        snapshot_state = {
            'precision': 4,
            'multiplier': 1,
        }
        print(f'Divisor before any snapshot: {self.frames.price_divisor({})}')
        print(f'Divisor for a currency snapshot: {self.frames.price_divisor(snapshot_state)}')
        topics = [
            (
                'dp|nse_cm|3045',
                32,
            ),
            (
                'if|nse_cm|Nifty 50',
                8,
            ),
            (
                'sf|nse_cm|3045',
                3,
            ),
            (
                'sf|nse_cm|3045',
                23,
            ),
        ]
        for topic, field_count in topics:
            fields = self.frames.fields_for(topic, field_count)
            print(f'{topic} with {field_count} values: {len(fields)} fields starting {fields[:3]}')


if __name__ == '__main__':
    ReadingResponsesExample().run()
