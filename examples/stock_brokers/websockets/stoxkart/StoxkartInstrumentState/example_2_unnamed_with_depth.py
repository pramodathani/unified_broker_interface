"""Builds a tick for an unnamed Stoxkart instrument with a book and no previous close.

A Stoxkart instrument whose name is an empty string is keyed by the `EXCHANGE:TOKEN` it was subscribed as. Its tick is always in full mode and carries a copy of the state's `depth`, so a later change to the book does not alter a tick already handed on. Without a previous close there is no percentage change.

This program fills a state's values and book by hand and builds one tick. It needs no stand-ins.

Notice the id, the `None` change and close, and that the tick's book is unchanged after the state's book is cleared.

Run it from the project root:

    python examples/stock_brokers/websockets/stoxkart/StoxkartInstrumentState/example_2_unnamed_with_depth.py
"""


from stock_brokers.websockets.stoxkart import (
    StoxkartInstrumentState,
)


class UnnamedWithDepthExample:
    """Builds a tick for an unnamed instrument with a book.

    Attributes:
        state (StoxkartInstrumentState): The state being shown.
    """

    def __init__(self):
        """Builds the state and fills its values and book.

        Returns:
            None: This method returns nothing.
        """
        self.state = StoxkartInstrumentState('MCX:565899', '')
        self.state.values['last_price'] = 6120.0
        self.state.values['volume'] = 8450
        self.state.depth['buy'] = [
            {
                'quantity': 3,
                'price': 6119.0,
                'orders': 2,
            },
        ]
        self.state.depth['sell'] = [
            {
                'quantity': 5,
                'price': 6121.0,
                'orders': 1,
            },
        ]

    def run(self):
        """Prints the tick, clears the state's book, and prints the tick's book again.

        Returns:
            None: This method returns nothing.
        """
        tick = self.state.tick(1000.0)
        print(f"Tick {tick['id']} in {tick['mode']} mode: last_price={tick['last_price']} change={tick['change']} close={tick['ohlc']['close']}")
        print(f"Book: {tick['depth']}")
        self.state.depth['buy'].clear()
        print(f"Book after the state's buy side was cleared: {tick['depth']}")


if __name__ == '__main__':
    UnnamedWithDepthExample().run()
