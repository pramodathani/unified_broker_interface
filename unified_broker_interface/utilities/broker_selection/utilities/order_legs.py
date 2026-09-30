"""The orders of a strategy that go to one broker together, so their margin can be priced as a whole."""


class OrderLegs:
    """Several orders sent one after another to the broker the first of them chooses, such as the four legs of an iron condor.

    A basket hands these to the placement of its first leg, which is the one that chooses the broker, so the funds check can ask whether that broker can afford the whole strategy rather than only its first order.

    Attributes:
        legs (list): One `(instrument_id, order)` tuple per leg, in the order they will be sent; each order is a `PlaceOrderRequest`.
        hedge_benefit (bool): Whether the caller asked for the legs to be priced together, so a hedge lowers the margin, at brokers known to allow it.
    """

    def __init__(self, legs, hedge_benefit=False):
        """Builds the legs.

        Args:
            legs (list): One `(instrument_id, order)` tuple per leg, in send order.
            hedge_benefit (bool): Whether to price the legs together.

        Returns:
            None: This method returns nothing.
        """
        self.legs = list(legs)
        self.hedge_benefit = bool(hedge_benefit)

    def instrument_ids(self):
        """Each leg's instrument id, in send order.

        Returns:
            list: The instrument ids (str).
        """
        instrument_ids = []
        for instrument_id, order in self.legs:
            instrument_ids.append(instrument_id)
        return instrument_ids

    def orders(self):
        """Each leg's order, in send order.

        Returns:
            list: The orders (PlaceOrderRequest).
        """
        orders = []
        for instrument_id, order in self.legs:
            orders.append(order)
        return orders
