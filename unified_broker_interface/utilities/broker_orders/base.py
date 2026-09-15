"""What every broker's order class shares: whether it can take an order, the one HTTP call, and the reading of error answers."""

import time

import requests

from unified_broker_interface.utilities.broker_orders.utilities.broker_answer import (
    BrokerAnswer,
)
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)


class BrokerOrders:
    """How one broker takes and cancels orders.

    One instance is built per broker per gunicorn worker, when the blueprint is built. Its constructor opens no connection, and the class reads no store: the blueprint reads Redis and passes the decoded login, settings, handle and stored order in.

    A subclass sets the class attributes and implements `build_place_request`, `build_cancel_request` and `read_order_id`, and overrides the other methods only where its broker differs.

    Attributes:
        BROKER_NAME (str): The broker's name, as the Redis hashes key it.
        IDENTIFIER_FIELD (str): The order handle field the broker's order request names the instrument by: `broker_token` or `order_symbol`.
        PLACE_SETTINGS_FIELDS (list): The account settings a place request needs.
        CANCEL_SETTINGS_FIELDS (list): The account settings a cancel request needs.
        MARKETS (dict): Each market the broker takes orders in, as `(exchange, asset class, kind)`, to the exchange or segment code its request carries.
        TAKES_AFTER_MARKET (bool): Whether the broker takes after-market orders.
        TAKES_TRIGGERED_ORDERS (bool): Whether the broker takes `SL` and `SL-M` orders.
        VERIFY_CERTIFICATE (bool): Whether the broker's TLS certificate is checked.
        TIMEOUT_SECONDS (tuple): The connect and read timeouts of the HTTP call.
        ERROR_CODE_KEYS (list): The body fields an error answer's code is read from, in order.
        ERROR_MESSAGE_KEYS (list): The body fields an error answer's message is read from, in order.
        session (requests.Session): The session every request to this broker is sent through, so later requests reuse its open connection.
    """

    BROKER_NAME = None
    IDENTIFIER_FIELD = 'order_symbol'
    PLACE_SETTINGS_FIELDS = []
    CANCEL_SETTINGS_FIELDS = []
    MARKETS = {}
    TAKES_AFTER_MARKET = True
    TAKES_TRIGGERED_ORDERS = True
    VERIFY_CERTIFICATE = True
    TIMEOUT_SECONDS = (
        3.05,
        10,
    )

    ERROR_CODE_KEYS = [
        'error_type',
        'errorType',
        'errorCode',
        'code',
        'stat',
    ]

    ERROR_MESSAGE_KEYS = [
        'message',
        'errorMessage',
        'emsg',
        'description',
        'errMsg',
    ]

    def __init__(self):
        """Builds the broker's order class with a session that has no connection open yet.

        Returns:
            None: This method returns nothing.
        """
        self.session = requests.Session()

    def missing_settings(self, settings, settings_fields):
        """Lists the account settings a request needs that the broker's settings lack.

        Args:
            settings (dict): The broker's decoded settings.
            settings_fields (list): The settings the request needs.

        Returns:
            list: The names of the missing settings, in order.
        """
        missing = []
        for settings_field in settings_fields:
            if not settings.get(settings_field):
                missing.append(settings_field)
        return missing

    def place_skip_reason(self, order, instrument, handle, login, settings):
        """Decides whether the broker can take an order, before anything is built.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            handle (object): The broker's order handle for the instrument, or None when the broker has none.
            login (object): The broker's decoded login, or None when Redis holds none or it is not JSON.
            settings (dict): The broker's decoded settings.

        Returns:
            str | None: Why the broker is passed over, or None when it can take the order.
        """
        market = instrument.market()
        if market not in self.MARKETS:
            return f'does not take {" ".join(market)} orders'
        if not isinstance(handle, dict):
            return 'has no mapping for the instrument'
        if not handle.get(self.IDENTIFIER_FIELD):
            return f'its mapping carries no {self.IDENTIFIER_FIELD}'
        handle_reason = self.handle_skip_reason(handle)
        if handle_reason is not None:
            return handle_reason
        if not isinstance(login, dict) or not login.get('access_token'):
            return 'has no login in Redis'
        login_reason = self.login_skip_reason(login)
        if login_reason is not None:
            return login_reason
        missing = self.missing_settings(settings, self.PLACE_SETTINGS_FIELDS)
        if missing:
            return 'has no ' + ', '.join(missing) + ' in its Redis settings'
        triggered = order.order_type in PlaceOrderRequest.TRIGGERED_ORDER_TYPES
        if triggered and not self.TAKES_TRIGGERED_ORDERS:
            return f'takes no {order.order_type} orders'
        if order.after_market and not self.TAKES_AFTER_MARKET:
            return 'takes no after-market orders'
        return None

    def handle_skip_reason(self, handle):
        """Checks what the broker needs from its order handle beyond the identifier field.

        Args:
            handle (dict): The broker's order handle.

        Returns:
            str | None: Why the handle cannot be used, or None.
        """
        del handle
        return None

    def login_skip_reason(self, login):
        """Checks what the broker needs from its login beyond the access token, when placing an order.

        Args:
            login (dict): The broker's decoded login.

        Returns:
            str | None: Why the login cannot be used, or None.
        """
        del login
        return None

    def cancel_problem(self, login, settings):
        """Decides whether a cancel can be sent with the broker's login and settings.

        Args:
            login (object): The broker's decoded login, or None.
            settings (dict): The broker's decoded settings.

        Returns:
            str | None: The error message answered with HTTP 503, or None when the cancel can be sent.
        """
        broker_name = self.BROKER_NAME
        if not isinstance(login, dict) or not login.get('access_token'):
            return f'{broker_name} has no login in Redis'
        login_problem = self.cancel_login_problem(login)
        if login_problem is not None:
            return login_problem
        missing = self.missing_settings(settings, self.CANCEL_SETTINGS_FIELDS)
        if missing:
            return (
                f'{broker_name} has no '
                + ', '.join(missing)
                + ' in its Redis settings'
            )
        return None

    def cancel_login_problem(self, login):
        """Checks what the broker needs from its login beyond the access token, when cancelling an order.

        Args:
            login (dict): The broker's decoded login.

        Returns:
            str | None: The error message, or None.
        """
        del login
        return None

    def build_place_request(self, order, instrument, handle, login, settings):
        """Builds the broker's place-order request.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            handle (dict): The broker's order handle for the instrument.
            login (dict): The broker's decoded login.
            settings (dict): The broker's decoded settings.

        Returns:
            BrokerRequest: The request, not yet sent.

        Raises:
            NotImplementedError: Always, in the base class.
        """
        raise NotImplementedError

    def build_cancel_request(self, order_id, stored_order, login, settings):
        """Builds the broker's cancel request.

        Args:
            order_id (str): The broker's order id.
            stored_order (StoredOrder): The order as the broker's order scripts keep it in Redis.
            login (dict): The broker's decoded login.
            settings (dict): The broker's decoded settings.

        Returns:
            BrokerRequest: The request, not yet sent.

        Raises:
            NotImplementedError: Always, in the base class.
        """
        raise NotImplementedError

    def read_order_id(self, response_fields):
        """Reads the order id from a successful place-order answer.

        Args:
            response_fields (dict): The broker's JSON body, or an empty dictionary.

        Returns:
            object: The order id as the broker sent it, or None.

        Raises:
            NotImplementedError: Always, in the base class.
        """
        raise NotImplementedError

    def read_refusal(self, response_fields):
        """Reads a refusal from an answer the broker sent with a success status.

        Args:
            response_fields (dict): The broker's JSON body, or an empty dictionary.

        Returns:
            object: The refusal message, or None when the body carries no refusal.
        """
        del response_fields
        return None

    def is_settled_refusal(self, error_code):
        """Whether a server error's code means the broker refused the order rather than failing to decide.

        Args:
            error_code (str): The code read from the error answer, or an empty string.

        Returns:
            bool: True when the order was certainly not placed.
        """
        del error_code
        return False

    def send(self, broker_request):
        """Sends the request once and decodes whatever came back.

        A connect timeout is `rejected`, because the request never left. Any other network error is `unknown`, because the broker may have acted on it.

        Args:
            broker_request (BrokerRequest): The request.

        Returns:
            BrokerAnswer: The answer, with `status_code` and `response_body` set when the broker answered.
        """
        answer = BrokerAnswer(time.perf_counter())
        response = None
        try:
            response = self.session.request(
                broker_request.method,
                broker_request.url,
                params=broker_request.params,
                data=broker_request.data,
                json=broker_request.json_body,
                headers=broker_request.headers,
                timeout=self.TIMEOUT_SECONDS,
                verify=broker_request.verify_certificate,
            )
        except requests.exceptions.ConnectTimeout as error:
            answer.outcome = 'rejected'
            answer.status_message = (
                f'could not connect to the broker, so nothing was sent: {error}'
            )
        except requests.exceptions.RequestException as error:
            answer.outcome = 'unknown'
            answer.status_message = f'{type(error).__name__}: {error}'
        answer.answered_at = time.perf_counter()
        if response is not None:
            answer.status_code = response.status_code
            try:
                answer.response_body = response.json()
            except ValueError:
                answer.response_body = response.text[:300]
        return answer

    def error_code(self, response_fields):
        """Reads the code from an error answer.

        Args:
            response_fields (dict): The broker's JSON body, or an empty dictionary.

        Returns:
            str: The code, or an empty string.
        """
        error_code = ''
        for key in self.ERROR_CODE_KEYS:
            if response_fields.get(key):
                error_code = str(response_fields.get(key))
                break
        nested_error = response_fields.get('error')
        if isinstance(nested_error, dict) and not error_code:
            error_code = str(nested_error.get('code') or '')
        return error_code

    def error_message(self, answer):
        """Reads the message from an error answer.

        Args:
            answer (BrokerAnswer): The answer.

        Returns:
            str: The message, or the body itself, cut to 300 characters.
        """
        response_fields = answer.response_fields()
        error_message = None
        for key in self.ERROR_MESSAGE_KEYS:
            if response_fields.get(key):
                error_message = str(response_fields.get(key))
                break
        nested_error = response_fields.get('error')
        if isinstance(nested_error, dict) and not error_message:
            error_message = nested_error.get('message')
        return str(error_message or answer.response_body)[:300]

    def send_place(self, broker_request):
        """Sends a place-order request and decides whether the order was placed.

        An error status below 500 is `rejected`, and so is a server error whose code the broker's rules settle. Any other server error is `unknown`. A success status is `rejected` when its body carries a refusal, `accepted` when it carries an order id, and `unknown` otherwise.

        Args:
            broker_request (BrokerRequest): The request.

        Returns:
            BrokerAnswer: The answer.
        """
        answer = self.send(broker_request)
        if answer.status_code is None:
            return answer
        response_fields = answer.response_fields()

        if answer.status_code >= 300:
            answer.status_message = self.error_message(answer)
            rejected = answer.status_code < 500
            if self.is_settled_refusal(self.error_code(response_fields)):
                rejected = True
            if rejected:
                answer.outcome = 'rejected'
            else:
                answer.outcome = 'unknown'
            return answer

        refusal = self.read_refusal(response_fields)
        order_id = self.read_order_id(response_fields)
        if order_id == 0 or order_id == '' or order_id == '0':
            order_id = None
        if order_id is not None:
            order_id = str(order_id)
        answer.order_id = order_id

        if refusal is not None:
            answer.outcome = 'rejected'
            answer.status_message = str(refusal)[:300]
        elif order_id is not None:
            answer.outcome = 'accepted'
        else:
            answer.outcome = 'unknown'
            answer.status_message = (
                f'the broker answered without an order id: {str(answer.response_body)[:300]}'
            )
        return answer

    def send_cancel(self, broker_request):
        """Sends a cancel request and decides whether the broker took it.

        An error status below 500 is `rejected` and a server error is `unknown`. A success status is `rejected` when its body carries a refusal and `accepted` otherwise, which means the broker took the request, not that the exchange has cancelled the order.

        Args:
            broker_request (BrokerRequest): The request.

        Returns:
            BrokerAnswer: The answer.
        """
        answer = self.send(broker_request)
        if answer.status_code is None:
            return answer

        if answer.status_code >= 300:
            answer.status_message = self.error_message(answer)
            if answer.status_code < 500:
                answer.outcome = 'rejected'
            else:
                answer.outcome = 'unknown'
            return answer

        refusal = self.read_refusal(answer.response_fields())
        if refusal is not None:
            answer.outcome = 'rejected'
            answer.status_message = str(refusal)[:300]
        else:
            answer.outcome = 'accepted'
        return answer
