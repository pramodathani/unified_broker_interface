"""Writes a margin calculator for a made-up broker and asks it about one order through a stand-in HTTP session.

A broker's calculator subclasses `BrokerMarginCalculator`, sets `BROKER_NAME` and `ORDER_CLASS`, and implements two methods: `build_order_request`, which turns a reference leg into the broker's request, and `read_order_margin`, which picks the margin out of its answer. `order_margin` joins them with `send`. The helpers `field` and `amount` walk into an answer and turn a figure into a positive decimal. This program borrows Zerodha's order class for its markets and quantity rules, and answers the request from a stand-in session, so nothing leaves the machine.

The program also calls the pieces `order_margin` is made of one by one: `build_order_request`, `send_once`, `field`, `amount` and `read_order_margin`, and `broker_quantity`, which converts units into the broker's terms.

Notice that `basket_margin` answers None, because this calculator does not set `TAKES_BASKETS`, and that `amount` turns the answer's text `167109.41` into a decimal.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/base/BrokerMarginCalculator/example_1_writing_a_calculator.py
"""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.zerodha import ZerodhaOrders
from unified_broker_interface.utilities.margin_calculators.base import (
    BrokerMarginCalculator,
)
from unified_broker_interface.utilities.margin_calculators.utilities.reference_leg import (
    ReferenceLeg,
)


class StandInResponse:
    """A response with a status and a JSON body.

    Attributes:
        status_code (int): The HTTP status.
        body (object): The decoded body.
        text (str): The body as text.
    """

    def __init__(self, status_code, body):
        """Builds the response.

        Args:
            status_code (int): The HTTP status.
            body (object): The decoded body.

        Returns:
            None: This method returns nothing.
        """
        self.status_code = status_code
        self.body = body
        self.text = str(body)

    def json(self):
        """The decoded body.

        Returns:
            object: The body.
        """
        return self.body


class StandInSession:
    """A session that records each request and answers with a fixed margin.

    Attributes:
        requests (list): Each request as `(method, url, json)`.
    """

    def __init__(self):
        """Builds the session.

        Returns:
            None: This method returns nothing.
        """
        self.requests = []

    def request(self, method, url, **options):
        """Records the request and answers it.

        Args:
            method (str): The HTTP method.
            url (str): The URL.
            **options: The headers, body and other options.

        Returns:
            StandInResponse: The answer.
        """
        self.requests.append((method, url, options.get('json')))
        return StandInResponse(200, {'result': {'required': '167109.41'}})


class MadeUpMarginCalculator(BrokerMarginCalculator):
    """A calculator for a broker that takes a symbol, a side and a quantity."""

    BROKER_NAME = 'zerodha'
    ORDER_CLASS = ZerodhaOrders

    def build_order_request(self, leg):
        """Builds the made-up broker's request.

        Args:
            leg (ReferenceLeg): The order.

        Returns:
            BrokerRequest: The request.
        """
        return BrokerRequest(
            'POST',
            'https://margin.example/orders',
            {},
            json_body={
                'symbol': leg.handle(self.BROKER_NAME).get('order_symbol'),
                'side': leg.transaction_type,
                'quantity': self.broker_quantity(leg),
            },
        )

    def read_order_margin(self, answer):
        """Reads `result.required`.

        Args:
            answer (object): The decoded answer.

        Returns:
            decimal.Decimal: The margin.
        """
        return self.amount(self.field(answer, 'result', 'required'), 'result.required')


class WritingACalculatorExample:
    """Asks the made-up calculator about a sold NIFTY future.

    Attributes:
        session (StandInSession): The stand-in session.
        calculator (MadeUpMarginCalculator): The calculator.
        leg (ReferenceLeg): The order.
    """

    def __init__(self):
        """Builds the session, the calculator and the leg.

        Returns:
            None: This method returns nothing.
        """
        self.session = StandInSession()
        login = {
            'access_token': 'stand-in-token',
        }
        settings = {
            'api_key': 'stand-in-key',
        }
        self.calculator = MadeUpMarginCalculator(login, settings, self.session)
        identity = {
            'segment': 'nse_equity_index_futures',
            'shape': 'future',
        }
        handles = {
            'zerodha': {
                'broker_token': '12468226',
                'order_symbol': 'NIFTY26OCTFUT',
                'lot_size': '65.0',
                'tick_size': '0.1',
            },
        }
        future = Instrument('28312010-2d68-5c8d-8b42-a66bc13a7816', identity, handles)
        self.leg = ReferenceLeg('NIFTY future sold', future, 'SELL', 'NRML', 65, decimal.Decimal('22833.7'))

    def run(self):
        """Asks for the order's margin and a basket's, and prints what was sent.

        Returns:
            None: This method returns nothing.
        """
        print(f'Takes the leg: {self.calculator.takes(self.leg)}')
        print(f'Order margin: {self.calculator.order_margin(self.leg)}')
        print(f'Basket margin: {self.calculator.basket_margin([self.leg])}')
        for method, url, body in self.session.requests:
            print(f'Sent {method} {url} {body}')
        print(f'Quantity in the broker\'s terms: {self.calculator.broker_quantity(self.leg)}')
        request = self.calculator.build_order_request(self.leg)
        response = self.calculator.send_once(request)
        answer = response.json()
        print(f'send_once answered HTTP {response.status_code}')
        print(f'field result.required: {self.calculator.field(answer, "result", "required")!r}')
        print(f'amount of it: {self.calculator.amount("167109.41", "result.required")!r}')
        print(f'read_order_margin: {self.calculator.read_order_margin(answer)}')


if __name__ == '__main__':
    WritingACalculatorExample().run()
