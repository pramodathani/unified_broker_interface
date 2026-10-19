"""Records the close of a sell stop that filled 0.60 below its trigger, and shows its slip and its row.

A `StopOutcome` is one fired protective stop and the fill that closed its position. This program builds the stop of 19 October 2026 at 13:26:25 on a NIFTY 22900 call, whose trigger was a best bid of 173.85 and whose own order filled at 173.25.

Notice that the slip is positive, because a sell below its trigger is worse, and that `row` carries the basis points the slip allowance is worked out from.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/stop_outcome/StopOutcome/example_1_a_stop_that_filled.py
"""

import datetime

from unified_broker_interface.utilities.execution_costs.stop_outcome import (
    StopOutcome,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class StopThatFilledExample:
    """Records and prints one stop's close.

    Attributes:
        outcome (StopOutcome): The fired stop.
    """

    def __init__(self):
        """Builds the fired stop.

        Returns:
            None: This method returns nothing.
        """
        self.outcome = StopOutcome(
            'd2d8217c-fa18-4e36-a65c-32787a5f6783',
            '065e67b5-b3f8-5374-a0bb-4ddc7786338d',
            'nse_equity_index_options',
            'SELL',
            'bid',
            '173.85',
            datetime.datetime(2026, 10, 19, 13, 26, 25, tzinfo=INDIA),
        )

    def run(self):
        """Prints the stop before and after its close is recorded.

        Returns:
            None: This method returns nothing.
        """
        print(f'Resolved before the close is recorded: {self.outcome.is_resolved()}')
        self.outcome.record_close('stop', 65, '173.25')
        print(f'Resolved: {self.outcome.is_resolved()}, closed by {self.outcome.closed_by}')
        print(f'Slip per unit: {self.outcome.slip()}')
        print(f'Slip as a share of the trigger: {self.outcome.slip_fraction():.6f}')
        print(f'Slip in basis points: {self.outcome.slip_basis_points()}')
        row = self.outcome.row()
        print(f'Row: {row["transaction_type"]} {row["trigger_field"]} trigger {row["trigger_price"]}, filled {row["filled_quantity"]} at {row["average_price"]}')


if __name__ == '__main__':
    StopThatFilledExample().run()
