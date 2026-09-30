"""Fyers' margin calculator: `POST /api/v3/multiorder/margin`."""

from unified_broker_interface.utilities.broker_orders.fyers import FyersOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.margin_calculators.base import (
    BrokerMarginCalculator,
)


class FyersMarginCalculator(BrokerMarginCalculator):
    """Asks Fyers what an order, or a basket, needs.

    One endpoint serves both: it takes a list under `data` and answers `margin_total`. Its documentation says a basket gets hedge benefit when the bought leg comes first, but on 2026-09-30 it priced an iron condor as its four legs added up in either order, which the calibration records as no hedge benefit.
    """

    BROKER_NAME = 'fyers'
    ORDER_CLASS = FyersOrders
    TAKES_BASKETS = True

    def fyers_order(self, leg):
        """One order in Fyers' form.

        Args:
            leg (ReferenceLeg): The order.

        Returns:
            dict: The order's fields.
        """
        return {
            'symbol': leg.handle(self.BROKER_NAME).get('order_symbol'),
            'qty': self.broker_quantity(leg),
            'side': self.broker_orders.SIDE_CODES[leg.transaction_type],
            'type': 1,
            'productType': self.broker_orders.PRODUCT_CODES[leg.product],
            'limitPrice': float(leg.price),
            'stopLoss': 0,
            'stopPrice': 0,
            'takeProfit': 0,
        }

    def build_basket_request(self, legs):
        """Builds `POST /api/v3/multiorder/margin` for one or more orders.

        Args:
            legs (list): The `ReferenceLeg` orders.

        Returns:
            BrokerRequest: The request.
        """
        orders = []
        for leg in legs:
            orders.append(self.fyers_order(leg))
        headers = self.broker_orders.headers(self.login, self.settings)
        headers['Content-Type'] = 'application/json'
        return BrokerRequest(
            'POST',
            'https://api-t1.fyers.in/api/v3/multiorder/margin',
            headers,
            json_body={
                'data': orders,
            },
        )

    def read_basket_margin(self, answer):
        """Reads `data.margin_total`.

        Args:
            answer (object): The decoded answer.

        Returns:
            decimal.Decimal: The margin.
        """
        return self.amount(self.field(answer, 'data', 'margin_total'), 'data.margin_total')

    def build_order_request(self, leg):
        """Builds the same request for a single order.

        Args:
            leg (ReferenceLeg): The order.

        Returns:
            BrokerRequest: The request.
        """
        return self.build_basket_request([
            leg,
        ])

    def read_order_margin(self, answer):
        """Reads `data.margin_total`.

        Args:
            answer (object): The decoded answer.

        Returns:
            decimal.Decimal: The margin.
        """
        return self.read_basket_margin(answer)
