"""Counts a morning's orders and fills at two brokers and prints each broker's order-to-trade ratio.

The order engine calls `count_sent` every time it sends a request to a broker and `count_traded` every time one of its orders fills, wholly or partly. `counts` then gives one entry per broker, which is what the engine writes into its closing log line.

This program plays out a short made-up morning: seven orders sent to Zerodha of which two traded, and three sent to Dhan of which all three traded. The class keeps its counts in memory and needs no data store, broker or clock, so there are no stand-ins.

Notice that Zerodha's ratio is 3.5, meaning three and a half requests for every fill, while Dhan's is exactly 1.0. The ratio is rounded to three decimal places.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_to_trade_ratio/OrderToTradeRatio/example_1_counting_a_mornings_orders.py
"""

from unified_broker_interface.utilities.order_engine.utilities.order_to_trade_ratio import (
    OrderToTradeRatio,
)


class MorningOrdersExample:
    """Feeds a morning of sent and filled orders into the counter and prints the result.

    Attributes:
        ratio_counter (OrderToTradeRatio): The counter being shown.
        morning (list): The events of the morning, as (broker name, what happened) pairs.
    """

    def __init__(self):
        """Builds an empty counter and the list of events to feed it.

        Returns:
            None: This method returns nothing.
        """
        self.ratio_counter = OrderToTradeRatio()
        self.morning = []
        for _ in range(7):
            self.morning.append(('zerodha', 'sent'))
        for _ in range(2):
            self.morning.append(('zerodha', 'traded'))
        for _ in range(3):
            self.morning.append(('dhan', 'sent'))
            self.morning.append(('dhan', 'traded'))

    def run(self):
        """Counts every event and prints the ratio per broker and the full summary.

        Returns:
            None: This method returns nothing.
        """
        for broker_name, what_happened in self.morning:
            if what_happened == 'sent':
                self.ratio_counter.count_sent(broker_name)
            else:
                self.ratio_counter.count_traded(broker_name)
        print(f'Zerodha ratio: {self.ratio_counter.ratio("zerodha")}')
        print(f'Dhan ratio: {self.ratio_counter.ratio("dhan")}')
        summary = self.ratio_counter.counts()
        for broker_name, entry in summary.items():
            print(f'{broker_name}: {entry}')


if __name__ == '__main__':
    MorningOrdersExample().run()
