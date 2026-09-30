"""Builds one-minute bars from a run of one-second price ticks and prints each bar as it closes.

A `BarBuilder` keeps all of its state in the dictionary of parameters it is given, which in the engine is the parent order's own parameters. This program uses a plain dictionary for that, feeds the builder a scripted series of prices at fixed Unix times, and prints the bar that closes whenever a tick falls into the next minute.

Nothing here needs a data store or a clock, because every tick carries its own time. Notice that the tick 59 seconds into the first minute still belongs to the first bar, and that the bar only closes when the tick at the start of the next minute arrives, and that the stored parameters hold every price as text so that they survive a trip through JSON.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/bar_builder/BarBuilder/example_1_building_one_minute_bars.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.bar_builder import (
    BarBuilder,
)


class OneMinuteBarsExample:
    """Feeds scripted ticks into a one-minute builder and prints the bars it closes.

    Attributes:
        parameters (dict): The stored state, standing in for a parent order's parameters.
        builder (BarBuilder): The builder being shown.
        ticks (list): Pairs of (Unix time, price text) to feed in order.
    """

    def __init__(self):
        """Builds a one-minute builder over empty parameters and a scripted list of ticks.

        Returns:
            None: This method returns nothing.
        """
        self.parameters = {}
        self.builder = BarBuilder(self.parameters, 60)
        self.ticks = [
            (1790000400, '2450.10'),
            (1790000415, '2452.40'),
            (1790000430, '2448.75'),
            (1790000459, '2449.90'),
            (1790000460, '2451.00'),
            (1790000490, '2455.25'),
            (1790000519, '2453.60'),
            (1790000520, '2453.00'),
        ]

    def run(self):
        """Feeds every tick and prints the closed bars and the bar still being built.

        Returns:
            None: This method returns nothing.
        """
        for moment, price_text in self.ticks:
            bar_start = self.builder.bar_start(moment)
            closed = self.builder.add(decimal.Decimal(price_text), moment)
            print(f'tick at {moment} price {price_text} falls in bar starting {bar_start:.0f}')
            if closed is not None:
                print(f'  closed bar: high {closed["high"]} low {closed["low"]} close {closed["close"]}')
        print(f'Bar being built: {self.builder.current_bar()}')
        print(f'Stored high as text: {self.parameters["bar_high"]!r}')
        print(f'Stored high read back: {self.builder.number("bar_high")}')
        print(f'Closed bars: {self.builder.closed_bars()}')
        print(f'Stored closed bars: {self.parameters["closed_bars"]}')


if __name__ == '__main__':
    OneMinuteBarsExample().run()
