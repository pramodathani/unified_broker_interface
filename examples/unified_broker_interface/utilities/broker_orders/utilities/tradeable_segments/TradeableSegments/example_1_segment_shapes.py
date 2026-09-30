"""Looks up a few segments in `TradeableSegments` to see whether orders are taken for them, and what shape and asset class each has.

The place route accepts an order only for an exchange in `EXCHANGES` and a bare segment in `SHAPES`. The shape decides which identity fields name the instrument: a `security` needs a symbol, a `future` an underlying and an expiry, and an `option` also a strike and an option type. The asset class decides which broker market table the order is looked up in.

Index segments are left out on purpose, because an index cannot be traded, and so is `uncategorised`. The program shows both refusals.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/tradeable_segments/TradeableSegments/example_1_segment_shapes.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.tradeable_segments import (
    TradeableSegments,
)


class SegmentShapesExample:
    """Prints the shape and asset class of a handful of segments.

    Attributes:
        bare_segments (list): The segment names to look up.
    """

    def __init__(self):
        """Lists the segments to look up.

        Returns:
            None: This method returns nothing.
        """
        self.bare_segments = [
            'equities',
            'equity_index_options',
            'currency_futures',
            'commodity_options',
            'exchange_traded_funds',
            'indices',
            'uncategorised',
        ]

    def run(self):
        """Prints each segment's shape and asset class, or that orders are not taken for it.

        Returns:
            None: This method returns nothing.
        """
        print(f'Exchanges: {TradeableSegments.EXCHANGES}')
        for bare_segment in self.bare_segments:
            if bare_segment not in TradeableSegments.SHAPES:
                print(f'{bare_segment}: orders are not taken')
                continue
            shape = TradeableSegments.SHAPES[bare_segment]
            asset_class = TradeableSegments.ASSET_CLASSES[bare_segment]
            print(f'{bare_segment}: shape={shape}, asset class={asset_class}')


if __name__ == '__main__':
    SegmentShapesExample().run()
