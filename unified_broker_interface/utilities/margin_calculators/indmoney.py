"""INDmoney's margin calculator: INDstocks' `GET /margin`."""

from unified_broker_interface.utilities.broker_orders.indmoney import IndmoneyOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.margin_calculators.base import (
    BrokerMarginCalculator,
)


class IndmoneyMarginCalculator(BrokerMarginCalculator):
    """Asks INDstocks what one order needs.

    The endpoint is a `GET` whose parameters go in a JSON body, every one of them a string, as its documentation says and as the live API accepted on 2026-09-30. It prices one order at a time and has no basket form. Its `available_balance` answered 0 for an account holding 9,754.97 that day, so only `total_margin` is read.
    """

    BROKER_NAME = 'indmoney'
    ORDER_CLASS = IndmoneyOrders

    def build_order_request(self, leg):
        """Builds `GET /margin` with the order in a JSON body.

        Args:
            leg (ReferenceLeg): The order.

        Returns:
            BrokerRequest: The request.
        """
        headers = self.broker_orders.headers(self.login)
        headers['Content-Type'] = 'application/json'
        return BrokerRequest(
            'GET',
            'https://api.indstocks.com/margin',
            headers,
            json_body={
                'segment': self.broker_orders.MARKETS[leg.instrument.market()],
                'exchange': leg.instrument.exchange.upper(),
                'securityID': str(leg.handle(self.BROKER_NAME).get('broker_token')),
                'txnType': leg.transaction_type,
                'quantity': str(self.broker_quantity(leg)),
                'price': str(leg.price),
                'product': self.broker_orders.PRODUCT_CODES[leg.product],
            },
        )

    def read_order_margin(self, answer):
        """Reads `data.total_margin`.

        Args:
            answer (object): The decoded answer.

        Returns:
            decimal.Decimal: The margin.
        """
        return self.amount(self.field(answer, 'data', 'total_margin'), 'data.total_margin')
