"""Builds the binary frames a Fyers quotes socket sends and the HSM topic names it subscribes.

`FyersHsmFrames` holds the byte layouts of Fyers' HSM market feed protocol, the one Fyers' own SDK speaks. The quotes socket uses it to build the authentication frame carrying the hsm key, the frame that selects full mode, the subscription frame listing topic names, and the frame acknowledging data messages. `topic_name` turns a symbol and its fytoken into a topic name: the fytoken's first four digits name the exchange segment and the digits from the eleventh on the exchange token, and an index uses the index name Fyers' SDK carries.

This program builds each frame and prints it as hex, and asks for the topic names of an equity, an index, and a symbol whose segment the feed does not carry. It needs no stand-ins, because the class only packs and unpacks bytes.

Notice that `NSE:SBIN-EQ` becomes `sf|nse_cm|3045`, that `NSE:NIFTY50-INDEX` becomes `if|nse_cm|Nifty 50`, and that an unknown segment gives None.

Run it from the project root:

    python examples/stock_brokers/websockets/fyers/FyersHsmFrames/example_1_building_frames.py
"""


from stock_brokers.websockets.fyers import (
    FyersHsmFrames,
)


class BuildingFramesExample:
    """Builds HSM frames and topic names and prints them.

    Attributes:
        frames (FyersHsmFrames): The frame builder being shown.
    """

    def __init__(self):
        """Builds the frame builder.

        Returns:
            None: This method returns nothing.
        """
        self.frames = FyersHsmFrames()

    def run(self):
        """Prints each frame as hex and each topic name.

        Returns:
            None: This method returns nothing.
        """
        print(f"Authentication frame: {self.frames.auth_frame('hsm-key-1').hex()}")
        print(f'Full mode frame: {self.frames.full_mode_frame().hex()}')
        topics = [
            self.frames.topic_name('NSE:SBIN-EQ', '10100000003045'),
            self.frames.topic_name('NSE:NIFTY50-INDEX', '101000000026000'),
            self.frames.topic_name('NSE:SOMETHING-EQ', '99990000001234'),
        ]
        print(f'Topic names: {topics}')
        print(f'Subscription frame: {self.frames.subscribe_frame(topics[:2]).hex()}')
        print(f'Acknowledgement of message 42: {self.frames.acknowledge_frame(42).hex()}')


if __name__ == '__main__':
    BuildingFramesExample().run()
