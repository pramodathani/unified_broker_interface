"""The Noren platform's margin calculator, which Flattrade and Shoonya share: `GetOrderMargin` and `GetBasketMargin`."""

from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.margin_calculators.base import (
    BrokerMarginCalculator,
)


class NorenMarginCalculator(BrokerMarginCalculator):
    """Asks a Noren broker what an order, or a basket, needs.

    A subclass sets `BROKER_NAME` and `ORDER_CLASS`; the URL, the account field and the body encoding come from the broker's order class. The single-order answer's `ordermargin` is the order's margin; when the account cannot afford it, `marginused` becomes the shortfall instead, so it is not read. A basket puts its first order at the top level and the others in `basketlists`, and answers `marginusedtrade`, the margin once the whole basket has traded.
    """

    TAKES_BASKETS = True

    def noren_order(self, leg):
        """One order's Noren fields.

        Args:
            leg (ReferenceLeg): The order.

        Returns:
            dict: The fields.
        """
        return {
            'exch': self.broker_orders.MARKETS[leg.instrument.market()],
            'tsym': leg.handle(self.BROKER_NAME).get('order_symbol'),
            'qty': str(self.broker_quantity(leg)),
            'prc': str(leg.price),
            'prd': self.broker_orders.PRODUCT_CODES[leg.product],
            'trantype': self.broker_orders.SIDE_CODES[leg.transaction_type],
            'prctyp': 'LMT',
        }

    def account_fields(self):
        """The user and account ids every Noren request starts with.

        Returns:
            dict: `uid` and `actid`.
        """
        account = str(self.settings.get(self.broker_orders.ACCOUNT_SETTINGS_FIELD))
        return {
            'uid': account,
            'actid': account,
        }

    def noren_request(self, endpoint, fields):
        """A Noren `POST` with the fields encoded as `jData` and the token as `jKey`.

        Args:
            endpoint (str): The endpoint's name, such as `GetOrderMargin`.
            fields (dict): The `jData` fields.

        Returns:
            BrokerRequest: The request.
        """
        return BrokerRequest(
            'POST',
            f'{self.broker_orders.BASE_URL}/{endpoint}',
            {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            data=self.broker_orders.encoded_body(fields, self.login),
        )

    def build_order_request(self, leg):
        """Builds `GetOrderMargin` for one order.

        Args:
            leg (ReferenceLeg): The order.

        Returns:
            BrokerRequest: The request.
        """
        fields = self.account_fields()
        fields.update(self.noren_order(leg))
        return self.noren_request('GetOrderMargin', fields)

    def read_order_margin(self, answer):
        """Reads `ordermargin`.

        Args:
            answer (object): The decoded answer.

        Returns:
            decimal.Decimal: The margin.
        """
        return self.amount(self.field(answer, 'ordermargin'), 'ordermargin')

    def build_basket_request(self, legs):
        """Builds `GetBasketMargin`, with the first order at the top level and the rest in `basketlists`.

        Args:
            legs (list): The `ReferenceLeg` orders.

        Returns:
            BrokerRequest: The request.
        """
        fields = self.account_fields()
        fields.update(self.noren_order(legs[0]))
        others = []
        for leg in legs[1:]:
            others.append(self.noren_order(leg))
        fields['basketlists'] = others
        return self.noren_request('GetBasketMargin', fields)

    def read_basket_margin(self, answer):
        """Reads `marginusedtrade`.

        Args:
            answer (object): The decoded answer.

        Returns:
            decimal.Decimal: The margin.
        """
        return self.amount(self.field(answer, 'marginusedtrade'), 'marginusedtrade')
