"""Groups every tradeable segment by asset class and shape, which shows at a glance what the order routes cover.

The two tables in `TradeableSegments` are keyed by the same bare segment names. Walking them together gives, for each asset class, how many segments of each shape the place route accepts. The `securities` asset class is the one whose lot sizes every broker agrees on; `currency` and `commodity` need the morning's contract size decision before an order is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/tradeable_segments/TradeableSegments/example_2_counting_by_asset_class.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.tradeable_segments import (
    TradeableSegments,
)


class CountingByAssetClassExample:
    """Counts the tradeable segments by asset class and shape.

    Attributes:
        counts (dict): Each asset class to a dictionary of shape counts.
    """

    def __init__(self):
        """Starts with no counts.

        Returns:
            None: This method returns nothing.
        """
        self.counts = {}

    def run(self):
        """Counts every segment and prints the table.

        Returns:
            None: This method returns nothing.
        """
        for bare_segment, shape in TradeableSegments.SHAPES.items():
            asset_class = TradeableSegments.ASSET_CLASSES[bare_segment]
            if asset_class not in self.counts:
                self.counts[asset_class] = {}
            shape_counts = self.counts[asset_class]
            shape_counts[shape] = shape_counts.get(shape, 0) + 1
        for asset_class in sorted(self.counts):
            print(f'{asset_class}: {self.counts[asset_class]}')
        print(f'Segments in all: {len(TradeableSegments.SHAPES)}')


if __name__ == '__main__':
    CountingByAssetClassExample().run()
