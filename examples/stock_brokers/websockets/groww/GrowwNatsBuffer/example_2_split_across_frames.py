"""Feeds a NATS message split across three websocket frames and shows the buffer waiting until it is whole.

A websocket frame may end in the middle of a NATS line or payload, so `GrowwNatsBuffer` keeps what it cannot use yet and hands a message out only once its whole payload has arrived. Bytes and text frames are both accepted.

This program feeds a message in three pieces as bytes, the second ending inside the payload, and then an `-ERR` line as text. It needs no stand-ins.

Notice that the first two feeds return nothing, and that the third returns the whole message.

Run it from the project root:

    python examples/stock_brokers/websockets/groww/GrowwNatsBuffer/example_2_split_across_frames.py
"""


from stock_brokers.websockets.groww import (
    GrowwNatsBuffer,
)


class SplitAcrossFramesExample:
    """Feeds a split message and an error line to a NATS buffer.

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
        """Feeds each piece and prints what each feed returned.

        Returns:
            None: This method returns nothing.
        """
        pieces = [
            b'MSG stocks/order/upd',
            b'ates.apex.subscription-77 1 10\r\n01234',
            b'56789\r\n',
            "-ERR 'Authorization Violation'\r\n",
        ]
        for piece in pieces:
            print(f'Fed {piece!r}: {self.buffer.feed(piece)}')


if __name__ == '__main__':
    SplitAcrossFramesExample().run()
