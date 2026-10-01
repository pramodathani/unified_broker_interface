"""Shows the three things that stop a participation order: a rejected slice, reaching its most slices, and a quote without volume.

A slice the broker rejects stops `ParticipationExecution`, as a rejected piece stops an iceberg, rather than inviting a fresh rejection on every tick, and `last_was_rejected` says so. The unfilled part of a cancelled slice is sent again by later slices, because `committed` counts only what filled of a finished slice. A quote that carries no volume sends nothing. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/participation_execution/ParticipationExecution/example_2_when_it_stops.py
"""

from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)
from unified_broker_interface.utilities.order_engine.utilities.participation_execution import (
    ParticipationExecution,
)


INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


class StandInParent:
    """Stands in for a plan order's parent, which only needs its instrument here.

    Attributes:
        instrument_id (str): The instrument the order trades.
    """

    def __init__(self):
        """Builds the parent.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = INSTRUMENT_ID


class StandInPlanOrder:
    """Stands in for the plan order an execution is asked about.

    Attributes:
        parent (StandInParent): The parent.
    """

    def __init__(self):
        """Builds the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.parent = StandInParent()


class PieceMaker:
    """Builds broker orders as the engine records them, in a chosen state."""

    def piece(self, number, quantity, state, filled):
        """One broker order.

        Args:
            number (int): Its number, for its id.
            quantity (int): Its quantity.
            state (str): Its state, such as `acknowledged` or `rejected`.
            filled (int): How much of it has filled.

        Returns:
            OrderLeg: The leg.
        """
        leg = OrderLeg(f'parent-1:{number}', 'root')
        leg.quantity = quantity
        leg.state = state
        leg.filled_quantity = filled
        return leg


class WhenItStopsExample:
    """Prints a participation order's answers when it should stop."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        execution = ParticipationExecution(50.0, 2)
        plan_order = StandInPlanOrder()
        maker = PieceMaker()
        quotes = {
            INSTRUMENT_ID: {
                'volume': 2000,
            },
        }
        rejected = [
            maker.piece(1, 5, 'rejected', 0),
        ]
        print(f'After a rejected slice: last was rejected {execution.last_was_rejected(rejected)}, due {execution.due_pieces(plan_order, {"counted_volume": 1000}, 100, rejected, quotes, 0.0)}')
        cancelled = [
            maker.piece(1, 40, 'cancelled', 15),
        ]
        print(f'After a cancelled slice of 40 that filled 15: committed {execution.committed(cancelled)}, due {execution.due_pieces(plan_order, {"counted_volume": 1990}, 100, cancelled, quotes, 0.0)}')
        two_slices = [
            maker.piece(1, 10, 'filled', 10),
            maker.piece(2, 10, 'filled', 10),
        ]
        print(f'After its most slices: more to send {execution.will_send_more({}, 80, two_slices)}')
        no_volume = {
            INSTRUMENT_ID: {
                'last_price': 1000.0,
            },
        }
        print(f'A quote without volume reads {execution.volume_of(plan_order, no_volume)} and sends {execution.due_pieces(plan_order, {"counted_volume": 1000}, 100, [], no_volume, 0.0)}')
        print(f'As a dry run shows it: {execution.described()}')


if __name__ == '__main__':
    WhenItStopsExample().run()
