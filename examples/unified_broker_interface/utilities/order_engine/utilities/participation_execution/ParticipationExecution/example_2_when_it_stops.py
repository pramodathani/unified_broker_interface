"""Shows the three things that stop a participation order: a rejected slice, reaching its most slices, and a quote without volume.

A slice the broker rejects stops `ParticipationExecution`, as a rejected piece stops an iceberg, rather than inviting a fresh rejection on every tick, and `last_was_rejected` says so. The unfilled part of a cancelled slice is sent again by later slices, because `committed` counts only what filled of a finished slice. A quote that carries no volume sends nothing.

Last, `lot_size` reads the lot every slice must be a whole number of, from the instrument's handle at the broker the plan's orders go to. A share trades one at a time, so its lot is 1; a stand-in index future that Zerodha lists with a lot of 75 answers 75, so a share of the volume under 75 would wait for more. Nothing is read from Redis or sent anywhere.

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


class StandInInstrument:
    """Stands in for a catalogue instrument, which only needs its brokers' handles here.

    Attributes:
        handles (dict): Each broker's handle, holding its `lot_size`.
    """

    def __init__(self, lot_size):
        """Builds an instrument traded at Zerodha in lots of a given size.

        Args:
            lot_size (int): The lot Zerodha lists.

        Returns:
            None: This method returns nothing.
        """
        self.handles = {
            'zerodha': {
                'lot_size': lot_size,
            },
        }


class StandInPlacement:
    """Stands in for the engine's placement, which only needs to find the instrument here.

    Attributes:
        lot_size (int): The lot the instrument it finds is listed with.
    """

    def __init__(self, lot_size):
        """Builds the stand-in.

        Args:
            lot_size (int): The lot the instrument it finds is listed with.

        Returns:
            None: This method returns nothing.
        """
        self.lot_size = lot_size

    def market_context(self, instrument_id, with_quote, with_settings):
        """Answers with the instrument and nothing else.

        Args:
            instrument_id (str): The instrument, unused.
            with_quote (bool): Unused.
            with_settings (bool): Unused.

        Returns:
            tuple: The instrument (StandInInstrument), no quote (None) and no settings (None).
        """
        del instrument_id, with_quote, with_settings
        return StandInInstrument(self.lot_size), None, None


class StandInPlanOrder:
    """Stands in for the plan order an execution is asked about.

    Attributes:
        parent (StandInParent): The parent.
        instrument_id (str): The instrument the order trades.
        placement (StandInPlacement): Where the lot size is looked up.
    """

    def __init__(self, lot_size=1):
        """Builds the stand-in.

        Args:
            lot_size (int): The lot the order's instrument is listed with.

        Returns:
            None: This method returns nothing.
        """
        self.parent = StandInParent()
        self.instrument_id = INSTRUMENT_ID
        self.placement = StandInPlacement(lot_size)

    def chosen_broker(self):
        """The broker the plan's orders go to.

        Returns:
            str: Zerodha.
        """
        return 'zerodha'


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
        future = StandInPlanOrder(75)
        print(f'lot_size at {plan_order.chosen_broker()}: {execution.lot_size(plan_order)} for a share, {execution.lot_size(future)} for the index future')


if __name__ == '__main__':
    WhenItStopsExample().run()
