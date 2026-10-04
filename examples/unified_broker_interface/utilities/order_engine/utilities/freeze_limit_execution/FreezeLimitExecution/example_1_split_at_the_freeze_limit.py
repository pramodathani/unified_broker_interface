"""Splits a buy of 250 at a broker whose freeze quantity is 100 into three orders of 84, 83 and 83, all for that broker.

`FreezeLimitExecution.due_pieces` chooses the broker through the placement first, reads its `freeze_quantity` with `freeze_quantity`, and keeps the broker in memory so the part sends every slice there. Nothing more is due once the slices are sent. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/freeze_limit_execution/FreezeLimitExecution/example_1_split_at_the_freeze_limit.py
"""

from unified_broker_interface.utilities.order_engine.utilities.freeze_limit_execution import (
    FreezeLimitExecution,
)


class StandInPrepared:
    """Stands in for a prepared placement: the broker chosen, the quantity in its terms, and a lot size that is not known, so the order is split in units.

    Attributes:
        broker_name (str): The broker.
        broker_quantity (int): The quantity in the broker's own units.
        units_per_lot (None): The units in one lot, not known here.
    """

    def __init__(self, broker_name, broker_quantity):
        """Builds the prepared placement.

        Args:
            broker_name (str): The broker.
            broker_quantity (int): The quantity in the broker's units.

        Returns:
            None: This method returns nothing.
        """
        self.broker_name = broker_name
        self.broker_quantity = broker_quantity
        self.units_per_lot = None


class StandInPlacement:
    """Stands in for the placement: a selector that picks Flattrade, and the freeze quantities brokers publish.

    Attributes:
        attributes (dict): Each broker's attributes for the instrument.
    """

    def __init__(self, attributes):
        """Builds the placement.

        Args:
            attributes (dict): Each broker's attributes.

        Returns:
            None: This method returns nothing.
        """
        self.attributes = attributes

    def prepare(self, order, instrument_id, broker_name):
        """Chooses Flattrade, unless a broker is given, and states the quantity in its units, which here are the same.

        Args:
            order (dict): The order.
            instrument_id (str): Unused.
            broker_name (str | None): The broker it must go to, or None.

        Returns:
            StandInPrepared: The broker and quantity.
        """
        del instrument_id
        return StandInPrepared(broker_name or 'flattrade', order['quantity'])

    def broker_attributes(self, instrument_id):
        """The brokers' attributes for the instrument.

        Args:
            instrument_id (str): Unused.

        Returns:
            dict: The attributes.
        """
        del instrument_id
        return self.attributes


class StandInContext:
    """Stands in for the order's view of the plan order.

    Attributes:
        instrument_id (str): The instrument.
        body (dict): The order's body.
        placement (StandInPlacement): The placement.
    """

    def __init__(self, attributes):
        """Builds the context.

        Args:
            attributes (dict): Each broker's attributes for the instrument.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = 'NIFTY FUTURE'
        self.body = {
            'transaction_type': 'BUY',
            'order_type': 'MARKET',
        }
        self.placement = StandInPlacement(attributes)

    def chosen_broker(self):
        """The broker the plan's orders went to, none yet.

        Returns:
            None: No broker has been chosen.
        """
        return None

    def read_order(self, body):
        """The body as an order, kept as it is here.

        Args:
            body (dict): The body.

        Returns:
            dict: The body.
        """
        return body


class SplitAtTheFreezeLimitExample:
    """Prints a split order."""

    def run(self):
        """Prints the slices.

        Returns:
            None: This method returns nothing.
        """
        execution = FreezeLimitExecution()
        context = StandInContext({'flattrade': {'freeze_quantity': '100'}})
        memory = {}
        execution.begin(context, memory, {}, 0.0)
        print(f'Reads quotes: {execution.needs_prices()}, paced by ticks: {execution.paced_by_ticks()}, grows by changing its order: {execution.changes_its_order_to_grow()}')
        print(f'Due: {execution.due_pieces(context, memory, 250, [], {}, 0.0, "BUY")}, memory {memory}')
        print(f'Once sent, more to send: {execution.will_send_more(memory, 0, ["a slice"])}, due {execution.due_pieces(context, memory, 250, ["a slice"], {}, 0.0, "BUY")}')
        print(f'As a dry run shows it: {execution.described()}')


if __name__ == '__main__':
    SplitAtTheFreezeLimitExample().run()
