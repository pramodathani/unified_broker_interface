"""Compares the slip of a sell stop and a buy stop, and of a stop whose close was never found.

The slip is signed so that a positive number is money lost: a sell stop loses when it fills below its trigger, and a buy stop, which protects a sold position, loses when it fills above. This program records one of each, and a third stop with no close.

Notice that the same 0.30 gap is a loss for both stops, and that a stop with no close has no slip at all rather than a slip of zero.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/stop_outcome/StopOutcome/example_2_sell_and_buy_stops.py
"""

import datetime

from unified_broker_interface.utilities.execution_costs.stop_outcome import (
    StopOutcome,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
FIRED_AT = datetime.datetime(2026, 10, 19, 14, 0, tzinfo=INDIA)


class SellAndBuyStopsExample:
    """Prints three stops' slips.

    Attributes:
        outcomes (list): The three `StopOutcome` objects.
    """

    def __init__(self):
        """Builds the three stops and records two closes.

        Returns:
            None: This method returns nothing.
        """
        sell = StopOutcome('sell-stop', 'option', 'nse_equity_index_options', 'SELL', 'bid', '100.00', FIRED_AT)
        sell.record_close('stop', 65, '99.70')
        buy = StopOutcome('buy-stop', 'option', 'nse_equity_index_options', 'BUY', 'ask', '100.00', FIRED_AT)
        buy.record_close('other_order', 65, '100.30')
        lost = StopOutcome('lost-stop', 'option', 'nse_equity_index_options', 'SELL', 'bid', '100.00', FIRED_AT)
        self.outcomes = [
            sell,
            buy,
            lost,
        ]

    def run(self):
        """Prints each stop's side, close and slip.

        Returns:
            None: This method returns nothing.
        """
        for outcome in self.outcomes:
            print(f'{outcome.parent_order_id}: {outcome.transaction_type} at {outcome.trigger_price}, closed by {outcome.closed_by} at {outcome.average_price}, slip {outcome.slip()} ({outcome.slip_basis_points()} bps)')


if __name__ == '__main__':
    SellAndBuyStopsExample().run()
