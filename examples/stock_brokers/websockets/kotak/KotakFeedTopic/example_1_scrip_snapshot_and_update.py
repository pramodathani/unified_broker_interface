"""Applies a scrip snapshot and an update to a `KotakFeedTopic` and reads its numbers and prices.

`KotakFeedTopic` keeps the latest values of one subscribed topic. `apply` takes a snapshot's or an update's numeric fields in field order, ignoring -2147483648, which Kotak sends for an unchanged field. `number` returns a field as sent, and `price` divides a price field by the topic's multiplier times ten to its precision, which for a scrip topic are fields 23 and 24.

This program applies a snapshot of an NSE equity with prices in paise (multiplier 1, precision 2), then an update that changes only the last price (field 5). It needs no stand-ins.

Notice that the volume (field 4) keeps its snapshot value after the update, and that a field never sent reads as None.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakFeedTopic/example_1_scrip_snapshot_and_update.py
"""


from stock_brokers.websockets.kotak import (
    KotakFeedTopic,
)


class ScripSnapshotAndUpdateExample:
    """Updates one scrip topic and reads it.

    Attributes:
        topic (KotakFeedTopic): The topic being shown.
    """

    def __init__(self):
        """Builds a scrip topic for RELIANCE with its trading symbol.

        Returns:
            None: This method returns nothing.
        """
        strings = {
            54: 'RELIANCE-EQ',
        }
        self.topic = KotakFeedTopic('sf', 'nse_cm|2885', strings)

    def run(self):
        """Applies the snapshot and the update and prints the fields after each.

        Returns:
            None: This method returns nothing.
        """
        snapshot = []
        for _ in range(25):
            snapshot.append(0)
        snapshot[4] = 1204500
        snapshot[5] = 295050
        snapshot[21] = 291000
        snapshot[23] = 1
        snapshot[24] = 2
        self.topic.apply(snapshot)
        print(f'{self.topic.kind} topic for {self.topic.instrument_token} named {self.topic.strings[54]}')
        print(f'After the snapshot: last price {self.topic.price(5)}, close {self.topic.price(21)}, volume {self.topic.number(4)}')
        unchanged = -2147483648
        update = [
            unchanged,
            unchanged,
            unchanged,
            unchanged,
            unchanged,
            295175,
        ]
        self.topic.apply(update)
        print(f'After the update: last price {self.topic.price(5)}, volume {self.topic.number(4)}')
        print(f'A field never sent: {self.topic.number(40)} and its price {self.topic.price(40)}')


if __name__ == '__main__':
    ScripSnapshotAndUpdateExample().run()
