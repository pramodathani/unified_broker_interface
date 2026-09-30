"""Builds the acknowledgements a Kotak quotes socket sends after every few data frames.

Kotak's connection response says after how many data frames it wants an acknowledgement. The quotes socket counts data frames and, at that count, sends `KotakFeedRequests.acknowledgement` (type 3) carrying the message number of the last data frame, as a four-byte signed field.

This program builds acknowledgements for three message numbers and reads each one back with `KotakFrameReader`. It needs no stand-ins.

Notice that every acknowledgement is ten bytes long and that only the last four change.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakFeedRequests/example_2_acknowledgements.py
"""


from stock_brokers.websockets.kotak import (
    KotakFeedRequests,
    KotakFrameReader,
)


class AcknowledgementsExample:
    """Builds and reads back acknowledgement frames.

    Attributes:
        requests (KotakFeedRequests): The request builder being shown.
    """

    def __init__(self):
        """Builds the request builder.

        Returns:
            None: This method returns nothing.
        """
        self.requests = KotakFeedRequests()

    def run(self):
        """Prints each acknowledgement and the message number read back from it.

        Returns:
            None: This method returns nothing.
        """
        message_numbers = [
            2,
            50,
            100000,
        ]
        for message_number in message_numbers:
            frame = self.requests.acknowledgement(message_number)
            reader = KotakFrameReader(frame)
            reader.read_unsigned(2)
            frame_type = reader.read_unsigned(1)
            reader.read_unsigned(1)
            reader.read_unsigned(1)
            reader.read_unsigned(2)
            print(f'{frame.hex()} is type {frame_type} acknowledging message {reader.read_signed_integer()}')


if __name__ == '__main__':
    AcknowledgementsExample().run()
