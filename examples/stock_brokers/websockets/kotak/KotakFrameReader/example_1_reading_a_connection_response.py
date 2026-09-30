"""Reads a Kotak HSM connection response field by field with `KotakFrameReader`.

`KotakFrameReader` is a cursor over one binary frame from Kotak's HSM feed. Each read takes the next bytes and moves `position` past them: `read_unsigned` reads a big-endian unsigned integer of a given width, `read_signed_integer` a four-byte signed one, and `read_text` a string of single-byte characters. Every frame starts with its length in two bytes and its type in one.

This program builds the connection response Kotak sends when it accepts a session, with an acknowledgement interval of 50, and reads it the way the quotes socket does. It needs no stand-ins.

Notice how `position` advances with each read and ends at the frame's length plus the two bytes of the length itself.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakFrameReader/example_1_reading_a_connection_response.py
"""


from stock_brokers.websockets.kotak import (
    KotakFrameReader,
)


class ReadingAConnectionResponseExample:
    """Reads one connection response.

    Attributes:
        reader (KotakFrameReader): The reader being shown.
    """

    def __init__(self):
        """Builds the frame and a reader over it.

        Returns:
            None: This method returns nothing.
        """
        status_field = bytes([1]) + (1).to_bytes(2, 'big') + b'K'
        acknowledgement_field = bytes([2]) + (4).to_bytes(2, 'big') + (50).to_bytes(4, 'big')
        content = bytes([1, 2]) + status_field + acknowledgement_field
        frame = len(content).to_bytes(2, 'big') + content
        print(f'Frame: {frame.hex()}')
        self.reader = KotakFrameReader(frame)

    def run(self):
        """Reads each field and prints it with the reader's position.

        Returns:
            None: This method returns nothing.
        """
        length = self.reader.read_unsigned(2)
        frame_type = self.reader.read_unsigned(1)
        field_count = self.reader.read_unsigned(1)
        print(f'length={length} type={frame_type} fields={field_count} position={self.reader.position}')
        field_id = self.reader.read_unsigned(1)
        status = self.reader.read_text(self.reader.read_unsigned(2))
        print(f'field {field_id}: status={status!r} position={self.reader.position}')
        field_id = self.reader.read_unsigned(1)
        acknowledge_every = self.reader.read_unsigned(self.reader.read_unsigned(2))
        print(f'field {field_id}: acknowledge every {acknowledge_every} data frames position={self.reader.position}')


if __name__ == '__main__':
    ReadingAConnectionResponseExample().run()
