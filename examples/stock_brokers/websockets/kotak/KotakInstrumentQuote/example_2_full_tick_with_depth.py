"""Adds a depth topic to a Kotak instrument and builds a full tick with its five-level book.

Once a Kotak instrument has a depth topic, `KotakInstrumentQuote.tick` reads up to five levels on each side from it, best first, and the tick switches to full mode. A level whose price and quantity were never sent is left out.

This program attaches a scrip topic and a depth topic that sent only three buy levels and two sell levels. It needs no stand-ins.

Notice the book's quantities and order counts, and that the missing levels are absent rather than empty.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakInstrumentQuote/example_2_full_tick_with_depth.py
"""


from stock_brokers.websockets.kotak import (
    KotakFeedTopic,
    KotakInstrumentQuote,
)


class FullTickWithDepthExample:
    """Builds a full tick from scrip and depth topics.

    Attributes:
        quote (KotakInstrumentQuote): The instrument being shown.
    """

    def __init__(self):
        """Builds the instrument with both topics.

        Returns:
            None: This method returns nothing.
        """
        self.quote = KotakInstrumentQuote('nse_cm|2885')
        self.quote.scrip = self.scrip_topic()
        depth = KotakFeedTopic('dp', 'nse_cm|2885', {})
        unchanged = -2147483648
        values = []
        for _ in range(34):
            values.append(unchanged)
        for level in range(3):
            values[2 + level] = 295000 - level * 5
            values[12 + level] = 100 + level
            values[22 + level] = 3 + level
        for level in range(2):
            values[7 + level] = 295100 + level * 5
            values[17 + level] = 200 + level
            values[27 + level] = 4 + level
        values[32] = 1
        values[33] = 2
        depth.apply(values)
        self.quote.depth = depth

    def scrip_topic(self):
        """A scrip topic of RELIANCE with a quote in paise.

        Returns:
            KotakFeedTopic: The topic.
        """
        topic = KotakFeedTopic('sf', 'nse_cm|2885', {})
        values = []
        for _ in range(25):
            values.append(0)
        values[2] = 1790311529
        values[3] = 1790311528
        values[4] = 1204500
        values[5] = 295050
        values[14] = 292500
        values[15] = 296000
        values[20] = 293000
        values[21] = 291000
        values[23] = 1
        values[24] = 2
        topic.apply(values)
        return topic

    def print_tick(self, tick):
        """Prints the main fields of a tick, or that there is none.

        Args:
            tick (dict | None): The tick.

        Returns:
            None: This method returns nothing.
        """
        if tick is None:
            print('No tick yet')
            return
        print(f"Tick {tick['id']} in {tick['mode']} mode: last_price={tick['last_price']} change={round(tick['change'], 4)} ohlc={tick['ohlc']}")
        print(f"  last_trade_time={tick['last_trade_time']} exchange_timestamp={tick['exchange_timestamp']} depth={tick['depth']}")

    def run(self):
        """Prints the full tick.

        Returns:
            None: This method returns nothing.
        """
        self.print_tick(self.quote.tick('RELIANCE-EQ'))


if __name__ == '__main__':
    FullTickWithDepthExample().run()
