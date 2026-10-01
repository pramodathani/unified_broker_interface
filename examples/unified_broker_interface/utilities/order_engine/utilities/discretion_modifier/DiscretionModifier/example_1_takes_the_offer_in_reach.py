"""Walks a buy showing 1000 with 0.25 of discretion through an offer that comes within reach.

`DiscretionModifier.take` does nothing while the offer is more than 0.25 above the visible price. When it comes within reach, the visible order is cancelled first and a taking order is sent a little past the offer, never past 1000.25. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/discretion_modifier/DiscretionModifier/example_1_takes_the_offer_in_reach.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.discretion_modifier import (
    DiscretionModifier,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)


INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


class StandInParent:
    """Stands in for a plan order's parent.

    Attributes:
        instrument_id (str): The instrument the order trades.
        body (dict): The caller's body.
    """

    def __init__(self):
        """Builds a buy of 10 at 1000.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = INSTRUMENT_ID
        self.body = {
            'transaction_type': 'BUY',
            'order_type': 'LIMIT',
            'price': 1000,
            'quantity': 10,
            'tag': 'mine',
        }


class StandInPlanOrder:
    """Stands in for the plan order, keeping every request it is asked to send.

    Attributes:
        parent (StandInParent): The parent.
        body (dict): The caller's body.
        requests (list): Every request, in order.
    """

    def __init__(self):
        """Builds the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.parent = StandInParent()
        self.body = self.parent.body
        self.requests = []

    def view(self, quotes):
        """The market, with a tick of five paise.

        Args:
            quotes (dict): The quotes, by instrument id.

        Returns:
            MarketView: The view.
        """
        return MarketView(quotes.get(INSTRUMENT_ID), decimal.Decimal('0.05'))

    def cancel_leg(self, leg, reason):
        """Keeps a cancel.

        Args:
            leg (OrderLeg): The order.
            reason (str): Why.

        Returns:
            bool: True, as a broker that accepted it.
        """
        self.requests.append(f'cancel {leg.leg_id}: {reason}')
        return True

    def reduce_leg(self, leg, quantity, reason):
        """Keeps a reduction.

        Args:
            leg (OrderLeg): The order.
            quantity (int): Its new total.
            reason (str): Why.

        Returns:
            bool: True, as a broker that accepted it.
        """
        self.requests.append(f'reduce {leg.leg_id} to {quantity}: {reason}')
        return True

    def read_order(self, body):
        """The body as an order, which the stand-in keeps as it is.

        Args:
            body (dict): The body.

        Returns:
            dict: The body.
        """
        return body

    def chosen_broker(self):
        """The broker the parent's orders go to.

        Returns:
            str: The broker.
        """
        return 'flattrade'

    def place_leg(self, role, order, started_at, broker):
        """Keeps a placement.

        Args:
            role (str): The part's path.
            order (dict): The body.
            started_at (float | None): Unused.
            broker (str): The broker.

        Returns:
            None: This method returns nothing.
        """
        del started_at
        self.requests.append(f'place for {role} at {broker}: {order["quantity"]} at {order["price"]}, tag {order.get("tag")}')


class StandInPart:
    """Stands in for the order part the discretion belongs to.

    Attributes:
        path (str): The part's path.
        keeps_tag (bool): Whether its orders carry the caller's tag.
        legs (list): Its broker orders.
    """

    def __init__(self, legs):
        """Builds the part.

        Args:
            legs (list): Its broker orders.

        Returns:
            None: This method returns nothing.
        """
        self.path = 'root'
        self.keeps_tag = True
        self.legs = legs

    def own_legs(self, parent):
        """Its broker orders.

        Args:
            parent (StandInParent): Unused.

        Returns:
            list: The legs.
        """
        del parent
        return self.legs


class BookMaker:
    """Builds quotes and the visible order."""

    def book(self, bid, offer):
        """The quotes a tick carries.

        Args:
            bid (float): The best bid.
            offer (float): The best offer.

        Returns:
            dict: The quotes, by instrument id.
        """
        return {
            INSTRUMENT_ID: {
                'depth': {
                    'buy': [
                        {
                            'price': bid,
                            'quantity': 100,
                        },
                    ],
                    'sell': [
                        {
                            'price': offer,
                            'quantity': 100,
                        },
                    ],
                },
            },
        }

    def visible(self, side, price, quantity, filled):
        """The visible resting order.

        Args:
            side (str): BUY or SELL.
            price (float): Its limit.
            quantity (int): Its quantity.
            filled (int): How much has filled.

        Returns:
            OrderLeg: The leg.
        """
        leg = OrderLeg('parent-1:1', 'root')
        leg.transaction_type = side
        leg.price = price
        leg.quantity = quantity
        leg.filled_quantity = filled
        leg.state = 'acknowledged'
        leg.broker_order_id = '26091500000021'
        return leg


class TakesTheOfferInReachExample:
    """Takes an offer with discretion."""

    def run(self):
        """Prints each tick and the requests.

        Returns:
            None: This method returns nothing.
        """
        discretion = DiscretionModifier(decimal.Decimal('0.25'), None)
        plan_order = StandInPlanOrder()
        maker = BookMaker()
        visible = maker.visible('BUY', 1000.00, 10, 0)
        part = StandInPart([visible])
        print(f'Reachable price: {discretion.reachable_price(visible)}')
        for offer in (1000.50, 1000.20):
            print(f'Offer {offer}: within reach {discretion.within_reach(decimal.Decimal(str(offer)), visible)}, took {discretion.take(plan_order, part, maker.book(1000.00, offer))}')
        for request in plan_order.requests:
            print(f'  {request}')
        print(f'As a dry run shows it: {discretion.described()}')


if __name__ == '__main__':
    TakesTheOfferInReachExample().run()
