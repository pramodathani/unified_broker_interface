"""Kotak's margin calculator: Neo's `POST /quick/user/check-margin`."""

import json

from unified_broker_interface.utilities.broker_orders.kotak import KotakOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.margin_calculators.base import (
    BrokerMarginCalculator,
)


class KotakMarginCalculator(BrokerMarginCalculator):
    """Asks Kotak Neo what one order needs.

    The request goes to the host the login names, like Kotak's orders, as a `jData` form field, with the session id also in the query string. The answer's `ordMrgn` is the order's own margin; `rmsVldtd` says `OK` or `NOT_OK` for whether the account could place it. Neo has no basket calculator.
    """

    BROKER_NAME = 'kotak'
    ORDER_CLASS = KotakOrders

    def build_order_request(self, leg):
        """Builds `POST {base_url}/quick/user/check-margin` for one order.

        Args:
            leg (ReferenceLeg): The order.

        Returns:
            BrokerRequest: The request.
        """
        kotak_fields = {
            'exSeg': self.broker_orders.MARKETS[leg.instrument.market()],
            'prc': str(leg.price),
            'prcTp': 'L',
            'prod': leg.product,
            'qty': str(self.broker_quantity(leg)),
            'tok': str(leg.handle(self.BROKER_NAME).get('broker_token')),
            'trnsTp': self.broker_orders.SIDE_CODES[leg.transaction_type],
            'trgPrc': '0',
            'brkName': 'KOTAK',
            'brnchId': 'ONLINE',
        }
        headers = self.broker_orders.headers(self.login)
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        return BrokerRequest(
            'POST',
            f'{self.broker_orders.base_url(self.login)}/quick/user/check-margin',
            headers,
            params={
                'sId': self.login.get('sid'),
            },
            data={
                'jData': json.dumps(kotak_fields),
            },
        )

    def read_order_margin(self, answer):
        """Reads `ordMrgn`.

        Args:
            answer (object): The decoded answer.

        Returns:
            decimal.Decimal: The margin.
        """
        return self.amount(self.field(answer, 'ordMrgn'), 'ordMrgn')
