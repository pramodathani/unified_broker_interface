"""Shows an order sent whole when the chosen broker publishes no freeze quantity, and one that would need more than twenty slices.

`FreezeLimitExecution.split` sends the order whole when the broker gives no figure, since guessing a limit from another broker could be wrong by a lot size, and refuses an order that would take more than twenty orders. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/freeze_limit_execution/FreezeLimitExecution/example_2_no_limit_and_too_many.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
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


class NoLimitAndTooManyExample:
    """Prints a whole order and a refusal."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        execution = FreezeLimitExecution()
        only_zerodha = StandInContext({'zerodha': {'freeze_quantity': '100'}})
        print(f'No figure from Flattrade: due {execution.due_pieces(only_zerodha, {}, 250, [], {}, 0.0, "BUY")}, its freeze quantity {execution.freeze_quantity(only_zerodha, "flattrade")}')
        try:
            execution.split(5000, 5000, 10)
        except RefusedRequestError as refusal:
            print(f'5,000 at a limit of 10: {refusal.status} {refusal.body["error"]}')


if __name__ == '__main__':
    NoLimitAndTooManyExample().run()
