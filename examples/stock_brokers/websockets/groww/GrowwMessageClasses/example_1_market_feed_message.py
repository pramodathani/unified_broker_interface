"""Builds Groww's market feed protobuf class, round-trips a price message through bytes, and turns it into a dictionary.

Groww's market feed payloads are protobuf `StocksSocketResponseProtoDto` messages. `GrowwMessageClasses.stocks_response_class` builds that class at runtime from Groww's file descriptor, which the module carries serialized, in a descriptor pool of its own so it cannot clash with any other protobuf classes. `as_dict` turns any decoded message into a plain dictionary with Groww's own field names, enums by name and every field present.

This program fills in a price message for RELIANCE, serializes it as the server would, decodes the bytes with the class, and prints the dictionary. It needs no stand-ins.

Notice that fields the program never set, such as `openInterest`, still appear with zero, and that `segment` and `exchange` come out as the names `CASH` and `NSE`.

Run it from the project root:

    python examples/stock_brokers/websockets/groww/GrowwMessageClasses/example_1_market_feed_message.py
"""


from stock_brokers.websockets.groww import (
    GrowwMessageClasses,
)


class MarketFeedMessageExample:
    """Round-trips one Groww market feed message.

    Attributes:
        message_classes (GrowwMessageClasses): The class builder being shown.
    """

    def __init__(self):
        """Builds the class builder.

        Returns:
            None: This method returns nothing.
        """
        self.message_classes = GrowwMessageClasses()

    def run(self):
        """Builds, serializes, decodes and prints a price message.

        Returns:
            None: This method returns nothing.
        """
        response_class = self.message_classes.stocks_response_class()
        print(f'Class: {response_class.DESCRIPTOR.full_name}')
        message = response_class()
        message.symbol = 'RELIANCE'
        message.segment = 0
        message.exchange = 1
        message.stockLivePrice.ltp = 295050
        message.stockLivePrice.close = 291000
        message.stockLivePrice.volume = 1204500
        payload = message.SerializeToString()
        print(f'Serialized to {len(payload)} bytes')
        decoded = response_class.FromString(payload)
        dictionary = self.message_classes.as_dict(decoded)
        print(f"symbol={dictionary['symbol']} segment={dictionary['segment']} exchange={dictionary['exchange']}")
        for field, value in sorted(dictionary['stockLivePrice'].items()):
            print(f'  {field}: {value}')


if __name__ == '__main__':
    MarketFeedMessageExample().run()
