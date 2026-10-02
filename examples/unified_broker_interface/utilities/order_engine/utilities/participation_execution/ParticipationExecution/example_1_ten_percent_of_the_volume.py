"""Walks a participation order of ten at ten percent through the day's volume rising tick by tick.

`ParticipationExecution.begin` starts counting from the volume in the instrument's live quote, so nothing traded before the order started counts. On each tick, `due_pieces` sends ten percent of the volume traded since the last slice, once that comes to a whole unit, and `committed` is how much the slices sent so far account for. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/participation_execution/ParticipationExecution/example_1_ten_percent_of_the_volume.py
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

    def __init__(self):
        """Builds an instrument traded one share at a time at Zerodha.

        Returns:
            None: This method returns nothing.
        """
        self.handles = {
            'zerodha': {
                'lot_size': 1,
            },
        }


class StandInPlacement:
    """Stands in for the engine's placement, which only needs to find the instrument here."""

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
        return StandInInstrument(), None, None


class StandInPlanOrder:
    """Stands in for the plan order an execution is asked about.

    Attributes:
        parent (StandInParent): The parent.
        instrument_id (str): The instrument the order trades.
        placement (StandInPlacement): Where the lot size is looked up.
    """

    def __init__(self):
        """Builds the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.parent = StandInParent()
        self.instrument_id = INSTRUMENT_ID
        self.placement = StandInPlacement()

    def chosen_broker(self):
        """The broker the plan's orders go to.

        Returns:
            str: Zerodha.
        """
        return 'zerodha'


class TenPercentOfTheVolumeExample:
    """Asks a participation order what to send as the volume rises."""

    def quotes_with_volume(self, volume):
        """The quotes a tick carries, with the day's volume so far.

        Args:
            volume (int): The day's traded volume.

        Returns:
            dict: The quotes, by instrument id.
        """
        return {
            INSTRUMENT_ID: {
                'volume': volume,
            },
        }

    def run(self):
        """Prints each tick.

        Returns:
            None: This method returns nothing.
        """
        execution = ParticipationExecution(10.0, 60)
        plan_order = StandInPlanOrder()
        print(f'Reads quotes: {execution.needs_prices()}, paced by ticks: {execution.paced_by_ticks()}, grows by changing its order: {execution.changes_its_order_to_grow()}')
        memory = {}
        execution.begin(plan_order, memory, self.quotes_with_volume(1000), 0.0)
        print(f'Counting starts from {memory["counted_volume"]}')
        pieces = []
        volumes = [
            1005,
            1050,
            1060,
            1110,
            1200,
        ]
        for volume in volumes:
            quotes = self.quotes_with_volume(volume)
            print(f'Volume {volume}: the quote reads {execution.volume_of(plan_order, quotes)}')
            due = execution.due_pieces(plan_order, memory, 10, pieces, quotes, 0.0)
            if due:
                leg = OrderLeg(f'parent-1:{len(pieces) + 1}', 'root')
                leg.quantity = due[0]
                leg.state = 'acknowledged'
                leg.filled_quantity = 0
                pieces.append(leg)
            print(f'  due {due}, counted up to {memory["counted_volume"]}, committed {execution.committed(pieces)}')
        print(f'More to send: {execution.will_send_more(memory, 10 - execution.committed(pieces), pieces)}')
        print(f'As a dry run shows it: {execution.described()}')


if __name__ == '__main__':
    TenPercentOfTheVolumeExample().run()
