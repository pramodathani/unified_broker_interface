"""Works ten units as two TWAP slices over a minute, each slice shown two at a time as an iceberg, and prints what falls due at each moment.

`NestedExecution.begin` starts the outer TWAP's clock. On each call `due_pieces` lets the outer execution release new slices, then asks each slice's iceberg what to send against that slice's own broker orders; `leg_slices` in the memory records which slice each broker order belongs to, in the order they are sent. `will_send_more` stays True until every slice is released and worked. `needs_prices`, `paced_by_ticks` and `changes_its_order_to_grow` combine the two executions, and `described` is how a dry run shows it. Stand-in broker orders are filled by hand, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/nested_execution/NestedExecution/example_1_twap_slices_shown_as_icebergs.py
"""

from unified_broker_interface.utilities.order_engine.utilities.iceberg_execution import (
    IcebergExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.nested_execution import (
    NestedExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.twap_execution import (
    TwapExecution,
)


class StandInLeg:
    """Stands in for one broker order: its quantity, what it filled and whether it has finished.

    Attributes:
        quantity (int): The quantity sent.
        filled_quantity (int): What has filled.
        finished (bool): Whether it can fill no more.
        state (str): `acknowledged` while resting, `filled` once filled.
    """

    def __init__(self, quantity):
        """Builds a resting broker order.

        Args:
            quantity (int): The quantity sent.

        Returns:
            None: This method returns nothing.
        """
        self.quantity = quantity
        self.filled_quantity = 0
        self.finished = False
        self.state = 'acknowledged'

    def fill(self):
        """Fills it completely.

        Returns:
            None: This method returns nothing.
        """
        self.filled_quantity = self.quantity
        self.finished = True
        self.state = 'filled'

    def is_finished(self):
        """Whether it can fill no more.

        Returns:
            bool: True once filled.
        """
        return self.finished


class TwapSlicesShownAsIcebergsExample:
    """Walks a nested execution through a minute."""

    def run(self):
        """Prints what falls due at each moment.

        Returns:
            None: This method returns nothing.
        """
        execution = NestedExecution(TwapExecution(2, 1.0), IcebergExecution(2, 0))
        print(f'needs prices {execution.needs_prices()}, paced {execution.paced_by_ticks()}, grows by changing an order {execution.changes_its_order_to_grow()}')
        print('described:', execution.described())
        memory = {}
        execution.begin(None, memory, {}, 0.0)
        legs = []
        moments = [
            0.0,
            1.0,
            2.0,
            30.0,
            31.0,
            32.0,
        ]
        for now in moments:
            due = execution.due_pieces(None, memory, 10, legs, {}, now)
            for quantity in due:
                legs.append(StandInLeg(quantity))
            print(f'at {now:>4}s: send {due}, slices {[slice_record["quantity"] for slice_record in memory["slices"]]}, leg slices {memory["leg_slices"]}')
            for leg in legs:
                if not leg.is_finished():
                    leg.fill()
        filled = 0
        for leg in legs:
            filled = filled + leg.filled_quantity
        remaining = 10 - filled
        print(f'every slice worked: will send more {execution.will_send_more(memory, remaining, legs)}')


if __name__ == '__main__':
    TwapSlicesShownAsIcebergsExample().run()
