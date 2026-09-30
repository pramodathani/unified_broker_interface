"""The class every broker's margin calculator subclasses."""

import decimal
import time

import requests


class MarginCalculatorError(Exception):
    """A broker's margin calculator could not be asked, or its answer could not be read."""


class BrokerMarginCalculator:
    """Asks one broker's own margin calculator what an order, or a basket of orders, needs.

    A subclass sets `BROKER_NAME` and `ORDER_CLASS`, and implements `build_order_request` and `read_order_margin`. A broker whose calculator prices several orders together sets `TAKES_BASKETS` and implements `build_basket_request` and `read_basket_margin`. Building a request and reading an answer are kept apart from sending, so both can be checked offline against answers recorded from the live brokers.

    The calculator only reads. It uses the login and settings every other process uses, never logs in, and sends nothing a broker could treat as an order.

    Attributes:
        BROKER_NAME (str): The broker, as the code spells it.
        ORDER_CLASS (type): The broker's `BrokerOrders` class, whose headers and quantity rules are reused.
        TAKES_BASKETS (bool): Whether the broker's calculator prices several orders together.
        PAUSE_SECONDS (float): How long to wait before each request, for a broker whose calculator is rate limited tightly.
        RATE_LIMITED_WAIT_SECONDS (float): How long to wait after an HTTP 429 before asking again.
        RATE_LIMITED_ATTEMPTS (int): How many times to ask in all when the broker keeps answering HTTP 429.
        TIMEOUT_SECONDS (float): How long a request may take.
        login (dict): The broker's decoded login.
        settings (dict): The broker's decoded settings.
        broker_orders (BrokerOrders): An instance of `ORDER_CLASS`.
        session (requests.Session): The HTTP session.
    """

    BROKER_NAME = None
    ORDER_CLASS = None
    TAKES_BASKETS = False
    PAUSE_SECONDS = 0.0
    RATE_LIMITED_WAIT_SECONDS = 20.0
    RATE_LIMITED_ATTEMPTS = 3
    TIMEOUT_SECONDS = 10.0

    def __init__(self, login, settings, session=None):
        """Builds the calculator.

        Args:
            login (dict): The broker's decoded login.
            settings (dict): The broker's decoded settings.
            session (requests.Session | None): The HTTP session, or None for a new one.

        Returns:
            None: This method returns nothing.
        """
        self.login = login
        self.settings = settings
        self.broker_orders = self.ORDER_CLASS()
        self.session = session or requests.Session()

    def takes(self, leg):
        """Whether the broker can be asked about a leg: it trades the leg's market, knows how to count its quantity, and has a handle for the instrument.

        Args:
            leg (ReferenceLeg): The leg.

        Returns:
            bool: True when the broker can price the leg.
        """
        market = leg.instrument.market()
        if market not in self.broker_orders.MARKETS:
            return False
        if not leg.instrument.is_securities_market():
            if self.broker_orders.QUANTITY_UNITS.get(market) is None:
                return False
            if leg.instrument.trusted_units_per_lot() is None:
                return False
        handle = leg.handle(self.BROKER_NAME)
        if not isinstance(handle, dict):
            return False
        return bool(handle.get(self.broker_orders.IDENTIFIER_FIELD))

    def broker_quantity(self, leg):
        """A leg's quantity in the broker's own terms.

        Args:
            leg (ReferenceLeg): The leg.

        Returns:
            int: The quantity the broker's request carries.
        """
        return self.broker_orders.broker_quantity(
            leg.units,
            leg.instrument,
            leg.handle(self.BROKER_NAME),
        )

    def order_margin(self, leg):
        """What the broker's calculator says one order needs.

        Args:
            leg (ReferenceLeg): The order.

        Returns:
            decimal.Decimal: The margin.

        Raises:
            MarginCalculatorError: When the request fails or the answer cannot be read.
        """
        answer = self.send(self.build_order_request(leg))
        return self.read_order_margin(answer)

    def basket_margin(self, legs):
        """What the broker's calculator says several orders need together.

        Args:
            legs (list): The `ReferenceLeg` orders, in send order.

        Returns:
            decimal.Decimal | None: The margin, or None when the broker has no basket calculator.

        Raises:
            MarginCalculatorError: When the request fails or the answer cannot be read.
        """
        if not self.TAKES_BASKETS:
            return None
        answer = self.send(self.build_basket_request(legs))
        return self.read_basket_margin(answer)

    def build_order_request(self, leg):
        """Builds the request for one order.

        Args:
            leg (ReferenceLeg): The order.

        Returns:
            BrokerRequest: The request.

        Raises:
            NotImplementedError: Always, in the base class.
        """
        raise NotImplementedError

    def read_order_margin(self, answer):
        """Reads the margin out of the answer for one order.

        Args:
            answer (object): The decoded JSON answer.

        Returns:
            decimal.Decimal: The margin.

        Raises:
            NotImplementedError: Always, in the base class.
        """
        raise NotImplementedError

    def build_basket_request(self, legs):
        """Builds the request for several orders.

        Args:
            legs (list): The `ReferenceLeg` orders.

        Returns:
            BrokerRequest: The request.

        Raises:
            NotImplementedError: Always, in the base class.
        """
        raise NotImplementedError

    def read_basket_margin(self, answer):
        """Reads the margin out of the answer for several orders.

        Args:
            answer (object): The decoded JSON answer.

        Returns:
            decimal.Decimal: The margin.

        Raises:
            NotImplementedError: Always, in the base class.
        """
        raise NotImplementedError

    def send(self, broker_request):
        """Sends a request and decodes its JSON answer, asking again after a wait when the broker answers HTTP 429.

        Args:
            broker_request (BrokerRequest): The request.

        Returns:
            object: The decoded answer.

        Raises:
            MarginCalculatorError: When the request fails, the status is not 200, or the body is not JSON.
        """
        response = None
        for attempt in range(self.RATE_LIMITED_ATTEMPTS):
            if attempt > 0:
                time.sleep(self.RATE_LIMITED_WAIT_SECONDS)
            elif self.PAUSE_SECONDS > 0:
                time.sleep(self.PAUSE_SECONDS)
            response = self.send_once(broker_request)
            if response.status_code != 429:
                break
        if response.status_code != 200:
            raise MarginCalculatorError(f'{self.BROKER_NAME} answered HTTP {response.status_code}: {response.text[:200]}')
        try:
            return response.json()
        except ValueError as error:
            raise MarginCalculatorError(f'{self.BROKER_NAME} answered with a body that is not JSON: {response.text[:200]}') from error

    def send_once(self, broker_request):
        """Sends a request once.

        Args:
            broker_request (BrokerRequest): The request.

        Returns:
            requests.Response: The response.

        Raises:
            MarginCalculatorError: When the broker cannot be reached.
        """
        try:
            return self.session.request(
                broker_request.method,
                broker_request.url,
                headers=broker_request.headers,
                params=broker_request.params,
                data=broker_request.data,
                json=broker_request.json_body,
                timeout=self.TIMEOUT_SECONDS,
                verify=broker_request.verify_certificate,
            )
        except requests.RequestException as error:
            raise MarginCalculatorError(f'{self.BROKER_NAME} could not be reached: {error}') from error

    def amount(self, value, field_name):
        """A margin figure from an answer, as a positive decimal.

        Args:
            value (object): The figure, a number or a numeric string.
            field_name (str): The field it came from, for the error.

        Returns:
            decimal.Decimal: The amount.

        Raises:
            MarginCalculatorError: When the figure is missing, not a number, or not above zero.
        """
        try:
            number = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError) as error:
            raise MarginCalculatorError(f'{self.BROKER_NAME} answered no number in {field_name}: {value!r}') from error
        if not number.is_finite() or number <= 0:
            raise MarginCalculatorError(f'{self.BROKER_NAME} answered {field_name} = {value!r}, which is not a margin')
        return number

    def field(self, answer, *path):
        """A value inside a decoded answer, following dictionary keys and list positions.

        Args:
            answer (object): The decoded answer.
            *path (str | int): The keys and positions to follow.

        Returns:
            object: The value.

        Raises:
            MarginCalculatorError: When a step of the path is missing.
        """
        value = answer
        for step in path:
            try:
                value = value[step]
            except (KeyError, IndexError, TypeError) as error:
                shown = '.'.join(str(part) for part in path)
                raise MarginCalculatorError(f'{self.BROKER_NAME} answered without {shown}: {str(answer)[:200]}') from error
        return value
