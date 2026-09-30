"""Reads signed integers, including Kotak's unchanged marker, and runs a `KotakFrameReader` past the end of its frame.

Kotak's numeric fields are four-byte signed integers, and -2147483648, the smallest one, means that a field in an update packet is unchanged. `read_signed_integer` reads them. Reading past the end of the frame raises `KotakTruncatedFrameError`, which says how long the frame was and where the read started, instead of returning short data.

This program reads a price, a negative change and the unchanged marker, then asks for four more bytes than are left. It needs no stand-ins.

Notice that the failed read leaves `position` where it was.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakFrameReader/example_2_signed_values_and_the_end_of_a_frame.py
"""


from stock_brokers.websockets.kotak import (
    KotakFrameReader,
    KotakTruncatedFrameError,
)


class SignedValuesAndTheEndOfAFrameExample:
    """Reads signed values and then reads too far.

    Attributes:
        reader (KotakFrameReader): The reader being shown.
    """

    def __init__(self):
        """Builds a frame of three signed integers and two spare bytes.

        Returns:
            None: This method returns nothing.
        """
        values = [
            295050,
            -1250,
            -2147483648,
        ]
        data = b''
        for value in values:
            data = data + value.to_bytes(4, 'big', signed=True)
        self.reader = KotakFrameReader(data + b'\x00\x07')

    def run(self):
        """Reads the three values, then a fourth that is not there.

        Returns:
            None: This method returns nothing.
        """
        for _ in range(3):
            print(f'Read {self.reader.read_signed_integer()}')
        try:
            self.reader.read_signed_integer()
        except KotakTruncatedFrameError as error:
            print(f'KotakTruncatedFrameError: {error}')
        print(f'Position after the failed read: {self.reader.position}')


if __name__ == '__main__':
    SignedValuesAndTheEndOfAFrameExample().run()
