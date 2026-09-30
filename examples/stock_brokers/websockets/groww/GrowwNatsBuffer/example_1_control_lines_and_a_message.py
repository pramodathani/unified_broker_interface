"""Feeds one websocket frame of NATS traffic to the buffer and prints the events it takes out.

NATS is line based: control lines end with CRLF, and a `MSG` line is followed by a payload of the length it declares. `GrowwNatsBuffer.feed` adds a websocket frame to the stream and returns, in order, an `info` event with the decoded INFO line, a `ping` event, an `error` event for an `-ERR` line, and a `message` event with the subject and payload of each whole `MSG`. Other control lines, such as `+OK` or `PONG`, produce nothing.

This program feeds one frame holding an INFO line, a PONG, a PING and a message. It needs no stand-ins.

Notice that the payload comes out as bytes exactly as long as the `MSG` line declared, even though it contains a CRLF of its own.

Run it from the project root:

    python examples/stock_brokers/websockets/groww/GrowwNatsBuffer/example_1_control_lines_and_a_message.py
"""


from stock_brokers.websockets.groww import (
    GrowwNatsBuffer,
)


class ControlLinesAndAMessageExample:
    """Feeds one frame to a NATS buffer.

    Attributes:
        buffer (GrowwNatsBuffer): The buffer being shown.
    """

    def __init__(self):
        """Builds an empty buffer.

        Returns:
            None: This method returns nothing.
        """
        self.buffer = GrowwNatsBuffer()

    def run(self):
        """Feeds the frame and prints each event.

        Returns:
            None: This method returns nothing.
        """
        frame = 'INFO {"nonce": "example-nonce", "headers": true}\r\nPONG\r\nPING\r\nMSG /ld/eq/nse/book.2885 2 7\r\nab\r\ncde\r\n'
        for event in self.buffer.feed(frame):
            print(event)


if __name__ == '__main__':
    ControlLinesAndAMessageExample().run()
