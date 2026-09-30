"""Catches `KotakTruncatedFrameError` as a plain `ValueError` while parsing a snapshot packet cut short.

Because `KotakTruncatedFrameError` subclasses `ValueError`, a caller that already handles malformed values can catch it without naming it. This program parses the start of a snapshot packet, as the quotes socket does, from bytes that stop halfway through the topic name.

It raises the error on purpose with a short packet and catches it as `ValueError`. It needs no stand-ins.

Notice that the topic id was read before the error, and that the class name still shows which error it was.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakTruncatedFrameError/example_2_caught_as_a_value_error.py
"""


from stock_brokers.websockets.kotak import (
    KotakFrameReader,
    KotakTruncatedFrameError,
)


class CaughtAsAValueErrorExample:
    """Parses a snapshot packet that stops inside its topic name.

    Attributes:
        reader (KotakFrameReader): The reader over the short packet.
    """

    def __init__(self):
        """Builds the start of a snapshot packet whose topic name is cut short.

        Returns:
            None: This method returns nothing.
        """
        name = b'sf|nse_cm|2885'
        packet = bytes([83]) + (7).to_bytes(4, 'big', signed=True) + bytes([len(name)]) + name[:6]
        self.reader = KotakFrameReader(packet)

    def parse(self):
        """Reads the packet type, the topic id and the topic name.

        Returns:
            tuple: The packet type, the topic id and the topic name.

        Raises:
            KotakTruncatedFrameError: When the packet ends inside the topic name.
        """
        packet_type = self.reader.read_unsigned(1)
        topic_id = self.reader.read_signed_integer()
        print(f'Read packet type {packet_type} for topic id {topic_id}')
        topic_name = self.reader.read_text(self.reader.read_unsigned(1))
        return packet_type, topic_id, topic_name

    def run(self):
        """Parses the packet and catches the error as a ValueError.

        Returns:
            None: This method returns nothing.
        """
        try:
            self.parse()
        except ValueError as error:
            print(f'Caught as ValueError: {type(error).__name__}: {error}')
            print(f'Is a KotakTruncatedFrameError: {isinstance(error, KotakTruncatedFrameError)}')


if __name__ == '__main__':
    CaughtAsAValueErrorExample().run()
