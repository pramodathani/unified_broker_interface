"""Measures volatility as the average true range of recent bars, including a gap between two bars.

An order that sizes its stop from volatility asks the `BarBuilder` for `average_true_range`. This program fills the builder's parameters with closed bars through `keep`, as a restart would find them already stored, and asks for the average over three bars before and after enough bars exist.

The average needs one more bar than the number of periods, because each true range looks back at the previous bar's close. Notice that the last bar opens well above the previous close, so its true range is the distance from that close to its high rather than its own small high-to-low span. The program also shows that a damaged stored entry is skipped by `closed_bars` instead of breaking the calculation.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/bar_builder/BarBuilder/example_2_average_true_range_with_a_gap.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.bar_builder import (
    BarBuilder,
)


class AverageTrueRangeExample:
    """Stores closed fifteen-minute bars and prints the average true range as they accumulate.

    Attributes:
        parameters (dict): The stored state, standing in for a parent order's parameters.
        builder (BarBuilder): The builder being shown.
        bars (list): The bars to keep, as (high, low, close) text triples.
    """

    def __init__(self):
        """Builds a fifteen-minute builder over empty parameters.

        Returns:
            None: This method returns nothing.
        """
        self.parameters = {}
        self.builder = BarBuilder(self.parameters, 900)
        self.bars = [
            (
                '100.0',
                '98.0',
                '99.0',
            ),
            (
                '101.0',
                '99.5',
                '100.5',
            ),
            (
                '102.0',
                '100.0',
                '101.5',
            ),
            (
                '108.0',
                '107.0',
                '107.5',
            ),
        ]

    def run(self):
        """Keeps each bar in turn and prints the three-bar average true range after each.

        Returns:
            None: This method returns nothing.
        """
        for high, low, close in self.bars:
            bar = {
                'high': decimal.Decimal(high),
                'low': decimal.Decimal(low),
                'close': decimal.Decimal(close),
            }
            self.builder.keep(bar)
            count = len(self.builder.closed_bars())
            average = self.builder.average_true_range(3)
            print(f'after {count} closed bars, three-bar average true range: {average}')
        self.parameters['closed_bars'].append([
            'not a price',
            '1',
            '1',
        ])
        print(f'Stored entries: {len(self.parameters["closed_bars"])}')
        print(f'Readable closed bars: {len(self.builder.closed_bars())}')
        print(f'Average true range still: {self.builder.average_true_range(3)}')
        print(f'No bar is being built yet: {self.builder.current_bar()}')


if __name__ == '__main__':
    AverageTrueRangeExample().run()
