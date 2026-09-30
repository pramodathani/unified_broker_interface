"""Wisdom Capital's margin calculator: the Symphony XTS platform's `POST /interactive/orders/margindetails`."""

from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.broker_orders.wisdom_capital import (
    WisdomCapitalOrders,
)
from unified_broker_interface.utilities.margin_calculators.base import (
    BrokerMarginCalculator,
)

EXCHANGE_NUMBERS = {
    'NSECM': 1,
    'NSEFO': 2,
    'NSECD': 3,
    'BSECM': 11,
    'BSEFO': 12,
    'BSECD': 13,
    'MCXFO': 51,
}


class WisdomCapitalMarginCalculator(BrokerMarginCalculator):
    """Asks Wisdom Capital's XTS server what an order, or a basket, needs.

    The endpoint takes a `portfolio` list, so one request serves both. Unlike XTS's order endpoint it names the exchange by number (`exchange`), not by segment name, and it needs `userID` and `orderSessionType`; a request built like an order is refused with "Instrument Informations count is 0". Its rate limit is tight: a second request within a second was refused with HTTP 429 on 2026-09-30, so each request waits three seconds first. The answer's object is spelt `brokerageDeatils` by the server itself. It answered zero for crude oil that day, which is read as no answer.
    """

    BROKER_NAME = 'wisdom_capital'
    ORDER_CLASS = WisdomCapitalOrders
    TAKES_BASKETS = True
    PAUSE_SECONDS = 3.0

    def xts_order(self, leg):
        """One order in the margin endpoint's form.

        Args:
            leg (ReferenceLeg): The order.

        Returns:
            dict: The order's fields.
        """
        segment = self.broker_orders.MARKETS[leg.instrument.market()]
        return {
            'exchange': EXCHANGE_NUMBERS[segment],
            'exchangeInstrumentId': int(str(leg.handle(self.BROKER_NAME).get('broker_token'))),
            'productType': leg.product,
            'orderType': 'LIMIT',
            'orderSide': leg.transaction_type,
            'quantity': self.broker_quantity(leg),
            'price': float(leg.price),
            'stopPrice': 0,
            'userID': str(self.settings.get('ucc_code')),
            'orderSessionType': 1,
        }

    def build_basket_request(self, legs):
        """Builds `POST /interactive/orders/margindetails` for one or more orders.

        Args:
            legs (list): The `ReferenceLeg` orders.

        Returns:
            BrokerRequest: The request.
        """
        orders = []
        for leg in legs:
            orders.append(self.xts_order(leg))
        headers = self.broker_orders.headers(self.login)
        headers['Content-Type'] = 'application/json'
        return BrokerRequest(
            'POST',
            'https://trade.wisdomcapital.in/interactive/orders/margindetails',
            headers,
            json_body={
                'clientID': str(self.settings.get('ucc_code')),
                'portfolio': orders,
            },
            verify_certificate=self.broker_orders.VERIFY_CERTIFICATE,
        )

    def read_basket_margin(self, answer):
        """Reads `result.brokerageDeatils.MarginRequired`.

        Args:
            answer (object): The decoded answer.

        Returns:
            decimal.Decimal: The margin.
        """
        required = self.field(answer, 'result', 'brokerageDeatils', 'MarginRequired')
        return self.amount(required, 'result.brokerageDeatils.MarginRequired')

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
