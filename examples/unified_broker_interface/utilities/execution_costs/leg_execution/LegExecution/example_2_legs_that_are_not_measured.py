"""Shows which legs have a fill to measure, and the sign a sell leg uses.

Only a leg that was sent and filled at a known price can be measured. A rejected leg never fills, and a leg the broker reported filled without a price yet cannot be priced. A sell gains when the price rises, so its side is -1, which turns every price move into a cost the other way round. This program builds the legs by hand, so it reads no database.

Notice that only the last leg is measurable.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/leg_execution/LegExecution/example_2_legs_that_are_not_measured.py
"""

import datetime
import decimal

from unified_broker_interface.utilities.execution_costs.leg_execution import (
    LegExecution,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class LegsThatAreNotMeasuredExample:
    """Builds three sell legs and prints whether each can be measured.

    Attributes:
        sent_at (datetime.datetime): When every leg was sent.
    """

    def __init__(self):
        """Builds the example.

        Returns:
            None: This method returns nothing.
        """
        self.sent_at = datetime.datetime(2026, 10, 6, 10, 20, 0, tzinfo=INDIA)

    def leg(self, name, outcome, filled_quantity, average_price):
        """Builds one sell leg from its request, its answer and one update.

        Args:
            name (str): The parent's name.
            outcome (str): The broker's answer.
            filled_quantity (int | None): The quantity filled.
            average_price (str | None): The fill price.

        Returns:
            LegExecution: The leg.
        """
        leg = LegExecution(name, '1', self.sent_at)
        leg.apply({
            'event': 'leg_requested',
            'time': self.sent_at,
            'instrument_id': 'b51c2f7e-5a0d-4c43-9e11-0f6a2d7c8b19',
            'transaction_type': 'SELL',
            'quantity': 65,
        })
        leg.apply({
            'event': 'leg_answered',
            'time': self.sent_at,
            'outcome': outcome,
        })
        price = None
        if average_price is not None:
            price = decimal.Decimal(average_price)
        leg.apply({
            'event': 'leg_update',
            'filled_quantity': filled_quantity,
            'average_price': price,
        })
        return leg

    def run(self):
        """Prints each leg's outcome and whether it can be measured.

        Returns:
            None: This method returns nothing.
        """
        legs = [
            self.leg('rejected', 'rejected', None, None),
            self.leg('filled without a price', 'accepted', 65, None),
            self.leg('filled', 'accepted', 65, '239.90'),
        ]
        for leg in legs:
            print(f'{leg.parent_order_id}: measurable {leg.is_filled()}, side {leg.side()}')


if __name__ == '__main__':
    LegsThatAreNotMeasuredExample().run()
