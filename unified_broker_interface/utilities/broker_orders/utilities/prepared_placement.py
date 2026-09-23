"""One order built for one broker, after the broker was chosen and before the request is sent."""


class PreparedPlacement:
    """An order that has been given a broker and a built request, but has not been sent.

    The step exists so that something can happen between choosing a broker and sending the order. A dry run answers from it without sending, and the order engine writes down what it is about to do before the request leaves, so a crash mid-send leaves a record of the attempt.

    Attributes:
        instrument_id (str): The instrument the order is for.
        broker_name (str): The chosen broker's name.
        broker_orders (BrokerOrders): The chosen broker's order class instance.
        broker_request (BrokerRequest): The request built for that broker, not yet sent.
        skipped (list): Each broker passed over before this one, as a dictionary with `broker` and `reason`.
    """

    def __init__(self, instrument_id, broker_orders, broker_request, skipped):
        """Builds the prepared placement.

        Args:
            instrument_id (str): The instrument the order is for.
            broker_orders (BrokerOrders): The chosen broker's order class instance.
            broker_request (BrokerRequest): The request built for that broker.
            skipped (list): Each broker passed over before this one.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = instrument_id
        self.broker_orders = broker_orders
        self.broker_name = broker_orders.BROKER_NAME
        self.broker_request = broker_request
        self.skipped = skipped
