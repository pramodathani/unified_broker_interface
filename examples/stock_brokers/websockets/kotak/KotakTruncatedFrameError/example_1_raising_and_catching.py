"""Raises `KotakTruncatedFrameError` by reading past the end of a frame and catches it.

`KotakTruncatedFrameError` means a binary frame from Kotak's HSM feed ended before a field it declared. `KotakFrameReader` raises it, and the quotes socket catches it for the whole frame, logs a warning and hands on the ticks of the packets it had already read. It is a `ValueError`, so code that treats any malformed value alike can catch it that way.

This program reads a text field whose declared length is longer than the bytes that follow. It needs no stand-ins.

Notice the message naming the frame's length, the size asked for and the position.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakTruncatedFrameError/example_1_raising_and_catching.py
"""


from stock_brokers.websockets.kotak import (
    KotakFrameReader,
    KotakTruncatedFrameError,
)


class RaisingAndCatchingExample:
    """Reads a text field that runs past the end of its frame.

    Attributes:
        reader (KotakFrameReader): The reader over the short frame.
    """

    def __init__(self):
        """Builds a frame whose text field declares 12 bytes but carries 4.

        Returns:
            None: This method returns nothing.
        """
        self.reader = KotakFrameReader(bytes([12]) + b'RELI')

    def run(self):
        """Reads the field and prints the error.

        Returns:
            None: This method returns nothing.
        """
        size = self.reader.read_unsigned(1)
        try:
            self.reader.read_text(size)
        except KotakTruncatedFrameError as error:
            print(f'Caught {type(error).__name__}: {error}')
            print(f'It is a ValueError: {isinstance(error, ValueError)}')


if __name__ == '__main__':
    RaisingAndCatchingExample().run()
