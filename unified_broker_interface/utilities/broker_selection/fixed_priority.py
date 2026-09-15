"""Every order is offered to the brokers in one configured order of preference."""

from unified_broker_interface.utilities.broker_selection.base import (
    BrokerSelector,
)
from utilities.configurations import api_configuration


class FixedPrioritySelector(BrokerSelector):
    """Offers every order first to the most preferred broker, then to the next, and so on.

    The preference comes from `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_PRIORITY`. Brokers it does not name follow the ones it does, in turn order. The selector reads no Redis, so it adds no command to an order's round trips.

    Attributes:
        priority (list): The configured broker names, most preferred first.
    """

    NAME = 'fixed_priority'

    def __init__(self):
        """Builds the selector with the preference read from configuration.

        Returns:
            None: This method returns nothing.
        """
        self.priority = []
        for broker_name in api_configuration['order_broker_priority']:
            if broker_name and broker_name not in self.priority:
                self.priority.append(broker_name)

    def ranked_brokers(self, order, instrument, rotation, redis_replies):
        """Lists the configured brokers first and the rest of the rotation after them.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            rotation (list): The broker names not excluded, in turn order.
            redis_replies (list): Unused, as the selector queues no commands.

        Returns:
            list: The broker names in order of preference.
        """
        del order
        del instrument
        del redis_replies
        ranked = []
        for broker_name in self.priority:
            if broker_name in rotation:
                ranked.append(broker_name)
        for broker_name in rotation:
            if broker_name not in ranked:
                ranked.append(broker_name)
        return ranked
