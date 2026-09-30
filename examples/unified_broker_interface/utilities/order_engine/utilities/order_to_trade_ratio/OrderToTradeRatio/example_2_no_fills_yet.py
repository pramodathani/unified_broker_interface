"""Shows that a broker with orders sent but nothing filled reports no ratio rather than a huge one.

A ratio is only meaningful once there is at least one fill to divide by. If the first order of the day is still resting at Fyers, dividing by zero fills would give infinity, which would read as a problem. The counter returns None instead, both from `ratio` and inside the `counts` summary.

This program sends two orders to Fyers without any fill, asks for the ratio, then records one fill and asks again. It also asks about Kotak, which the engine has never used; that broker has no ratio and does not appear in `counts` at all, because the summary only lists brokers something was sent to. The counter needs no stand-ins.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_to_trade_ratio/OrderToTradeRatio/example_2_no_fills_yet.py
"""

from unified_broker_interface.utilities.order_engine.utilities.order_to_trade_ratio import (
    OrderToTradeRatio,
)


class NoFillsYetExample:
    """Asks for a ratio before and after the first fill at one broker.

    Attributes:
        ratio_counter (OrderToTradeRatio): The counter being shown.
    """

    def __init__(self):
        """Builds an empty counter.

        Returns:
            None: This method returns nothing.
        """
        self.ratio_counter = OrderToTradeRatio()

    def run(self):
        """Prints the ratio and summary before and after one fill.

        Returns:
            None: This method returns nothing.
        """
        self.ratio_counter.count_sent('fyers')
        self.ratio_counter.count_sent('fyers')
        print(f'Fyers before any fill: {self.ratio_counter.ratio("fyers")}')
        print(f'Summary: {self.ratio_counter.counts()}')
        self.ratio_counter.count_traded('fyers')
        print(f'Fyers after one fill: {self.ratio_counter.ratio("fyers")}')
        print(f'Summary: {self.ratio_counter.counts()}')
        print(f'Kotak, never used: {self.ratio_counter.ratio("kotak")}')


if __name__ == '__main__':
    NoFillsYetExample().run()
