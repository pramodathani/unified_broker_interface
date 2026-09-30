"""Shows how `send` waits out an HTTP 429, and how it reports a failed status, a body that is not JSON, and an unfinished subclass.

A broker's calculator can be rate limited tightly: Wisdom Capital refused a second request within a second on 2026-09-30. `send` therefore asks again after `RATE_LIMITED_WAIT_SECONDS` when the answer is HTTP 429, up to `RATE_LIMITED_ATTEMPTS` times in all, and raises `MarginCalculatorError` for any other failure, which the calibration logs and treats as not measured. This program sets the wait to zero and scripts the stand-in session's answers, so it runs at once and needs no network.

Notice that the first request is asked twice and succeeds, and that the base class's own request builders and answer readers raise `NotImplementedError`.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/base/BrokerMarginCalculator/example_2_rate_limits_and_failures.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.broker_orders.zerodha import ZerodhaOrders
from unified_broker_interface.utilities.margin_calculators.base import (
    BrokerMarginCalculator,
    MarginCalculatorError,
)


class StandInResponse:
    """A response with a status and a body.

    Attributes:
        status_code (int): The HTTP status.
        text (str): The body as text.
        body (object | None): The decoded body, or None when the body is not JSON.
    """

    def __init__(self, status_code, text, body=None):
        """Builds the response.

        Args:
            status_code (int): The HTTP status.
            text (str): The body as text.
            body (object | None): The decoded body.

        Returns:
            None: This method returns nothing.
        """
        self.status_code = status_code
        self.text = text
        self.body = body

    def json(self):
        """The decoded body.

        Returns:
            object: The body.

        Raises:
            ValueError: When the body is not JSON.
        """
        if self.body is None:
            raise ValueError('not JSON')
        return self.body


class ScriptedSession:
    """A session that answers with scripted responses, in order.

    Attributes:
        responses (list): The responses still to give.
        asked (int): How many requests were made.
    """

    def __init__(self, responses):
        """Builds the session.

        Args:
            responses (list): The responses.

        Returns:
            None: This method returns nothing.
        """
        self.responses = list(responses)
        self.asked = 0

    def request(self, method, url, **options):
        """Gives the next scripted response.

        Args:
            method (str): The HTTP method.
            url (str): The URL.
            **options: The request's options.

        Returns:
            StandInResponse: The response.
        """
        del method
        del url
        del options
        self.asked = self.asked + 1
        return self.responses.pop(0)


class ImpatientCalculator(BrokerMarginCalculator):
    """A calculator that asks again at once after an HTTP 429."""

    BROKER_NAME = 'zerodha'
    ORDER_CLASS = ZerodhaOrders
    RATE_LIMITED_WAIT_SECONDS = 0.0


class RateLimitsAndFailuresExample:
    """Sends one request four times against different scripted answers.

    Attributes:
        request (BrokerRequest): The request.
    """

    def __init__(self):
        """Builds the request.

        Returns:
            None: This method returns nothing.
        """
        self.request = BrokerRequest('POST', 'https://margin.example/orders', {}, json_body={})

    def attempt(self, description, responses):
        """Sends the request against scripted answers and prints what happened.

        Args:
            description (str): What the answers are.
            responses (list): The scripted responses.

        Returns:
            None: This method returns nothing.
        """
        session = ScriptedSession(responses)
        calculator = ImpatientCalculator({}, {}, session)
        try:
            answer = calculator.send(self.request)
            print(f'{description}: answer {answer} after {session.asked} requests')
        except MarginCalculatorError as error:
            print(f'{description}: MarginCalculatorError after {session.asked} requests: {error}')

    def run(self):
        """Tries four sets of answers, then the unfinished base class.

        Returns:
            None: This method returns nothing.
        """
        self.attempt('429 then 200', [StandInResponse(429, 'slow down'), StandInResponse(200, '{}', {'ok': True})])
        self.attempt('429 three times', [StandInResponse(429, 'slow down')] * 3)
        self.attempt('HTTP 500', [StandInResponse(500, 'server error')])
        self.attempt('not JSON', [StandInResponse(200, '<html>')])
        calculator = ImpatientCalculator({}, {}, ScriptedSession([]))
        try:
            calculator.build_order_request(None)
        except NotImplementedError:
            print('build_order_request is left to each broker: NotImplementedError')
        try:
            calculator.read_order_margin(None)
        except NotImplementedError:
            print('read_order_margin is left to each broker: NotImplementedError')
        try:
            calculator.build_basket_request(None)
        except NotImplementedError:
            print('build_basket_request is left to each broker: NotImplementedError')
        try:
            calculator.read_basket_margin(None)
        except NotImplementedError:
            print('read_basket_margin is left to each broker: NotImplementedError')


if __name__ == '__main__':
    RateLimitsAndFailuresExample().run()
