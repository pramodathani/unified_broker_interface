"""Zerodha's margin calculator: Kite's `POST /margins/orders` and `POST /margins/basket`."""

from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.broker_orders.zerodha import ZerodhaOrders
from unified_broker_interface.utilities.margin_calculators.base import (
    BrokerMarginCalculator,
)


class ZerodhaMarginCalculator(BrokerMarginCalculator):
    """Asks Kite what an order, or a basket, needs.

    Both endpoints take a JSON list of orders. The single-order answer has one entry per order with a `total`; the basket answer has `initial`, the margin before any spread benefit, and `final`, after it, which is the figure a hedged strategy is charged. Positions already held are left out of the basket (`consider_positions=false`), so the answer is the strategy's own margin whatever the account holds.
    """

    BROKER_NAME = 'zerodha'
    ORDER_CLASS = ZerodhaOrders
    TAKES_BASKETS = True

    def kite_order(self, leg):
        """One order in Kite's form.

        Args:
            leg (ReferenceLeg): The order.

        Returns:
            dict: The order's fields.
        """
        return {
            'exchange': self.broker_orders.MARKETS[leg.instrument.market()],
            'tradingsymbol': leg.handle(self.BROKER_NAME).get('order_symbol'),
            'transaction_type': leg.transaction_type,
            'variety': 'regular',
            'product': leg.product,
            'order_type': 'LIMIT',
            'quantity': self.broker_quantity(leg),
            'price': float(leg.price),
            'trigger_price': 0,
        }

    def headers(self):
        """Kite's session headers, with the JSON content type the margin endpoints need.

        Returns:
            dict: The headers.
        """
        headers = self.broker_orders.headers(self.login, self.settings)
        headers['Content-Type'] = 'application/json'
        return headers

    def build_order_request(self, leg):
        """Builds `POST /margins/orders` for one order.

        Args:
            leg (ReferenceLeg): The order.

        Returns:
            BrokerRequest: The request.
        """
        return BrokerRequest(
            'POST',
            'https://api.kite.trade/margins/orders',
            self.headers(),
            json_body=[
                self.kite_order(leg),
            ],
        )

    def read_order_margin(self, answer):
        """Reads the first order's `total`.

        Args:
            answer (object): The decoded answer.

        Returns:
            decimal.Decimal: The margin.
        """
        return self.amount(self.field(answer, 'data', 0, 'total'), 'data[0].total')

    def build_basket_request(self, legs):
        """Builds `POST /margins/basket` for several orders, leaving out positions already held.

        Args:
            legs (list): The `ReferenceLeg` orders.

        Returns:
            BrokerRequest: The request.
        """
        orders = []
        for leg in legs:
            orders.append(self.kite_order(leg))
        return BrokerRequest(
            'POST',
            'https://api.kite.trade/margins/basket',
            self.headers(),
            params={
                'consider_positions': 'false',
                'mode': 'compact',
            },
            json_body=orders,
        )

    def read_basket_margin(self, answer):
        """Reads the basket's `final` total, after any spread benefit.

        Args:
            answer (object): The decoded answer.

        Returns:
            decimal.Decimal: The margin.
        """
        return self.amount(self.field(answer, 'data', 'final', 'total'), 'data.final.total')
