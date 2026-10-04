"""Splits NIFTY orders at the freeze limit of 3,511 units in whole lots of 65, and refuses one whose single lot is already above the limit.

`FreezeLimitExecution.split` works out the most lots one slice may carry from the freeze quantity, and shares the order's lots out as evenly as whole lots allow, so 55 lots goes as 28 and 27 rather than 1,788 and 1,787 units, which the lot check would refuse. Without a lot size it falls back to sharing units. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/freeze_limit_execution/FreezeLimitExecution/example_3_split_in_whole_lots.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.freeze_limit_execution import (
    FreezeLimitExecution,
)


class SplitInWholeLotsExample:
    """Prints the slices of several NIFTY orders, in units and in lots."""

    def run(self):
        """Prints each order's slices, then the refusal for a lot above the limit.

        Returns:
            None: This method returns nothing.
        """
        execution = FreezeLimitExecution()
        lot = 65
        freeze_quantity = 3511
        for lots in [
            54,
            55,
            150,
            154,
        ]:
            units = lots * lot
            slices = execution.split(units, units, freeze_quantity, lot)
            in_lots = []
            for size in slices:
                in_lots.append(size // lot)
            print(f'{lots} lots ({units} units): slices {slices}, which are {in_lots} lots')
        print(f'55 lots with no lot size known: {execution.split(3575, 3575, freeze_quantity)}')
        try:
            execution.split(150, 150, 50, 75)
        except RefusedRequestError as error:
            print(f'150 units in lots of 75 under a limit of 50: refused, {error}')


if __name__ == '__main__':
    SplitInWholeLotsExample().run()
