"""Builds a normalized tick from a Kotak instrument's scrip topic, and shows there is none before it.

`KotakInstrumentQuote` pairs one instrument's scrip topic and depth topic and turns their latest values into a normalized tick with `tick`. There is no tick until the scrip snapshot has arrived, because the scrip carries the prices. Without a depth topic the tick is in quote mode with an empty book. The quotes socket passes the instrument's trading symbol as the name, and a tick without one is keyed by its `EXCHANGE|TOKEN`.

This program asks for a tick before and after attaching a scrip topic, with and without a name. It needs no stand-ins.

Notice that the percentage change is computed from the last price and the close, and that the trade and feed times are the epochs the scrip carried.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakInstrumentQuote/example_1_tick_from_the_scrip_topic.py
"""


from stock_brokers.websockets.kotak import (
    KotakFeedTopic,
    KotakInstrumentQuote,
)


class TickFromTheScripTopicExample:
    """Builds ticks for one instrument before and after its scrip topic.

    Attributes:
        quote (KotakInstrumentQuote): The instrument being shown.
    """

    def __init__(self):
        """Builds the instrument with no topics.

        Returns:
            None: This method returns nothing.
        """
        self.quote = KotakInstrumentQuote('nse_cm|2885')

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
        """Prints the tick before the scrip topic, then with and without a name.

        Returns:
            None: This method returns nothing.
        """
        self.print_tick(self.quote.tick('RELIANCE-EQ'))
        self.quote.scrip = self.scrip_topic()
        self.print_tick(self.quote.tick('RELIANCE-EQ'))
        self.print_tick(self.quote.tick(None))
        print(f'Instrument {self.quote.instrument_token} has depth: {self.quote.depth is not None}')


if __name__ == '__main__':
    TickFromTheScripTopicExample().run()
