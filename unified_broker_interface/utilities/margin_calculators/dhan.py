"""Dhan's margin calculator: `POST /v2/margincalculator` and `POST /v2/margincalculator/multi`."""

from unified_broker_interface.utilities.broker_orders.dhan import DhanOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.margin_calculators.base import (
    BrokerMarginCalculator,
)


class DhanMarginCalculator(BrokerMarginCalculator):
    """Asks Dhan what an order, or a basket, needs.

    The multi-order endpoint's documentation names its fields two ways; the live API accepted only `scripList` and `includeOrder` on 2026-09-30, and answers in camelCase rather than the snake_case the documentation shows. Positions and open orders are left out, so the answer is the basket's own margin.
    """

    BROKER_NAME = 'dhan'
    ORDER_CLASS = DhanOrders
    TAKES_BASKETS = True

    def dhan_order(self, leg):
        """One order in Dhan's form.

        Args:
            leg (ReferenceLeg): The order.

        Returns:
            dict: The order's fields.
        """
        return {
            'dhanClientId': str(self.settings.get('client_id')),
            'exchangeSegment': self.broker_orders.MARKETS[leg.instrument.market()],
            'transactionType': leg.transaction_type,
            'quantity': self.broker_quantity(leg),
            'productType': self.broker_orders.PRODUCT_CODES[leg.product],
            'securityId': str(leg.handle(self.BROKER_NAME).get('broker_token')),
            'price': float(leg.price),
            'triggerPrice': 0,
        }

    def headers(self):
        """Dhan's session headers, with the JSON content type.

        Returns:
            dict: The headers.
        """
        headers = self.broker_orders.headers(self.login)
        headers['Content-Type'] = 'application/json'
        return headers

    def build_order_request(self, leg):
        """Builds `POST /v2/margincalculator` for one order.

        Args:
            leg (ReferenceLeg): The order.

        Returns:
            BrokerRequest: The request.
        """
        return BrokerRequest(
            'POST',
            'https://api.dhan.co/v2/margincalculator',
            self.headers(),
            json_body=self.dhan_order(leg),
        )

    def read_order_margin(self, answer):
        """Reads `totalMargin`.

        Args:
            answer (object): The decoded answer.

        Returns:
            decimal.Decimal: The margin.
        """
        return self.amount(self.field(answer, 'totalMargin'), 'totalMargin')

    def build_basket_request(self, legs):
        """Builds `POST /v2/margincalculator/multi` for several orders, leaving out positions and open orders.

        Args:
            legs (list): The `ReferenceLeg` orders.

        Returns:
            BrokerRequest: The request.
        """
        orders = []
        for leg in legs:
            orders.append(self.dhan_order(leg))
        return BrokerRequest(
            'POST',
            'https://api.dhan.co/v2/margincalculator/multi',
            self.headers(),
            json_body={
                'dhanClientId': str(self.settings.get('client_id')),
                'includePosition': False,
                'includeOrder': False,
                'scripList': orders,
            },
        )

    def read_basket_margin(self, answer):
        """Reads the basket's `totalMargin`.

        Args:
            answer (object): The decoded answer.

        Returns:
            decimal.Decimal: The margin.
        """
        return self.amount(self.field(answer, 'totalMargin'), 'totalMargin')
