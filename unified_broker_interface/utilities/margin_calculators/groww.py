"""Groww's margin calculator: `POST /v1/margins/detail/orders`."""

import decimal

from unified_broker_interface.utilities.broker_orders.groww import GrowwOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.margin_calculators.base import (
    BrokerMarginCalculator,
)


class GrowwMarginCalculator(BrokerMarginCalculator):
    """Asks Groww what an order, or a basket of futures and options, needs.

    The segment goes in the query string, `CASH` or `FNO`, and the body is a list of orders. The answer's `total_requirement` includes brokerage and charges, which are taken off so the figure is margin alone; it also splits the margin into SPAN, exposure and option premium.
    """

    BROKER_NAME = 'groww'
    ORDER_CLASS = GrowwOrders
    TAKES_BASKETS = True

    def groww_order(self, leg):
        """One order in Groww's form.

        Args:
            leg (ReferenceLeg): The order.

        Returns:
            dict: The order's fields.
        """
        return {
            'trading_symbol': leg.handle(self.BROKER_NAME).get('order_symbol'),
            'transaction_type': leg.transaction_type,
            'quantity': self.broker_quantity(leg),
            'price': float(leg.price),
            'order_type': 'LIMIT',
            'product': leg.product,
            'exchange': leg.instrument.exchange.upper(),
        }

    def build_basket_request(self, legs):
        """Builds `POST /v1/margins/detail/orders` for one or more orders in one segment.

        Args:
            legs (list): The `ReferenceLeg` orders.

        Returns:
            BrokerRequest: The request.
        """
        orders = []
        for leg in legs:
            orders.append(self.groww_order(leg))
        headers = self.broker_orders.headers(self.login)
        headers['Content-Type'] = 'application/json'
        headers['X-API-VERSION'] = '1.0'
        return BrokerRequest(
            'POST',
            'https://api.groww.in/v1/margins/detail/orders',
            headers,
            params={
                'segment': self.broker_orders.MARKETS[legs[0].instrument.market()],
            },
            json_body=orders,
        )

    def read_basket_margin(self, answer):
        """Reads `payload.total_requirement` less `payload.brokerage_and_charges`.

        Args:
            answer (object): The decoded answer.

        Returns:
            decimal.Decimal: The margin.
        """
        total = self.amount(self.field(answer, 'payload', 'total_requirement'), 'payload.total_requirement')
        charges = decimal.Decimal(str(self.field(answer, 'payload', 'brokerage_and_charges') or 0))
        return total - charges

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
        """Reads the margin the same way as for a basket.

        Args:
            answer (object): The decoded answer.

        Returns:
            decimal.Decimal: The margin.
        """
        return self.read_basket_margin(answer)
