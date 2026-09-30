"""Builds ticks from a Stoxkart instrument's state, and shows that an unchanged state gives no tick.

`StoxkartInstrumentState` holds the latest value of every field Stoxkart's packets have given for one instrument in `values`, and its book in `depth`. `tick` builds a normalized tick from them, but only once a trade packet has supplied a last price, and only when the tick differs from the previous one apart from `received_at`, so the stream never repeats itself.

This program fills the state's values by hand, as `StoxkartPacketDecoder` would, and asks for a tick four times. It needs no stand-ins. `received_at` is a fixed number here; the stream passes the time it decoded the frame.

Notice that there is no tick before the last price, that the second call with nothing changed gives none, and that a changed price gives one again.

Run it from the project root:

    python examples/stock_brokers/websockets/stoxkart/StoxkartInstrumentState/example_1_ticks_only_when_changed.py
"""


from stock_brokers.websockets.stoxkart import (
    StoxkartInstrumentState,
)


class TicksOnlyWhenChangedExample:
    """Asks one instrument state for ticks as its values change.

    Attributes:
        state (StoxkartInstrumentState): The state being shown.
    """

    def __init__(self):
        """Builds the state for RELIANCE.

        Returns:
            None: This method returns nothing.
        """
        self.state = StoxkartInstrumentState('NSE:2885', 'NSE:RELIANCE')

    def print_tick(self, tick):
        """Prints the main fields of a tick, or that there is none.

        Args:
            tick (dict | None): The tick.

        Returns:
            None: This method returns nothing.
        """
        if tick is None:
            print('No tick')
            return
        print(f"Tick {tick['id']} on {tick['exchange']}: last_price={tick['last_price']} change={tick['change']} ohlc={tick['ohlc']} received_at={tick['received_at']}")

    def run(self):
        """Prints the tick before a price, after one, unchanged, and after a change.

        Returns:
            None: This method returns nothing.
        """
        print(f'Instrument {self.state.instrument} named {self.state.name} on {self.state.exchange}')
        self.print_tick(self.state.tick(1000.0))
        self.state.values['last_price'] = 2950.5
        self.state.values['previous_close'] = 2910.0
        self.print_tick(self.state.tick(1001.0))
        self.print_tick(self.state.tick(1002.0))
        self.state.values['last_price'] = 2951.0
        self.print_tick(self.state.tick(1003.0))
        print(f'Values held: {self.state.values}')


if __name__ == '__main__':
    TicksOnlyWhenChangedExample().run()
