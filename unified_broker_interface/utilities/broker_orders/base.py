"""What every broker's order class shares: whether it can take, modify or cancel an order, the one HTTP call, and the reading of error answers."""

import decimal
import json
import re
import threading
import time
import urllib.parse
import warnings

import requests
import urllib3.exceptions
import urllib3.util.wait

from unified_broker_interface.utilities.broker_orders.utilities.broker_answer import (
    BrokerAnswer,
)
from unified_broker_interface.utilities.broker_orders.utilities.connection_pool import (
    IdleLimitedAdapter,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    OrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    OrderNotReadyError,
)


class BrokerOrders:
    """How one broker takes, modifies and cancels orders.

    One instance is built per broker per gunicorn worker, and one per order engine. Its constructor opens no connection, and the class reads no store: the caller reads Redis and passes the login, settings, handle and stored order in, decoding the login and the settings with the two methods below.

    A subclass sets the class attributes and implements `build_place_request`, `build_cancel_request` and `read_order_id`, lists `MODIFIABLE_FIELDS` and implements `build_modify_request` when it modifies orders, and overrides the other methods only where its broker differs.

    Attributes:
        BROKER_NAME (str): The broker's name, as the Redis hashes key it.
        IDENTIFIER_FIELD (str): The order handle field the broker's order request names the instrument by: `broker_token` or `order_symbol`.
        PLACE_SETTINGS_FIELDS (list): The account settings a place request needs.
        CANCEL_SETTINGS_FIELDS (list): The account settings a cancel request needs.
        MODIFY_SETTINGS_FIELDS (list): The account settings a modify request needs.
        MODIFIABLE_FIELDS (list): The fields of `ModifyOrderRequest.MODIFIABLE_FIELD_NAMES` the broker's modify request can change; empty when the broker's modify request is not built, which is answered with HTTP 501.
        MODIFY_ORDER_TYPES (list): The order types a modification can change an order to.
        MARKETS (dict): Each market the broker takes orders in, as `(exchange, asset class, kind)`, to the exchange or segment code its request carries.
        QUANTITY_UNITS (dict): Each currency or commodity market in `MARKETS` to how the broker's order API counts quantity there: `lots`, `units` (quotation units, as the route takes them) or `broker_lot_size` (lots times the broker's own lot size). A currency or commodity market without an entry passes the broker over.
        TAKES_AFTER_MARKET (bool): Whether the broker takes after-market orders.
        TAKES_TRIGGERED_ORDERS (bool): Whether the broker takes `SL` and `SL-M` orders.
        VERIFY_CERTIFICATE (bool): Whether the broker's TLS certificate is checked.
        TIMEOUT_SECONDS (tuple): The connect and read timeouts of the HTTP call.
        ERROR_CODE_KEYS (list): The body fields an error answer's code is read from, in order.
        ERROR_MESSAGE_KEYS (list): The body fields an error answer's message is read from, in order.
        MAXIMUM_IDLE_SECONDS (float): How long a pooled connection may sit idle and still carry a request; an older one is closed and a new connection opened instead, well before the broker's server would close it.
        WARM_URL (str | None): The public URL a warming ping is sent to when no request has named this broker's host yet, or None when the broker cannot be warmed.
        WARM_INTERVAL_SECONDS (float): How often a warming ping is sent, shorter than `MAXIMUM_IDLE_SECONDS`.
        WARM_TIMEOUT_SECONDS (tuple): The connect and read timeouts of a warming ping.
        WARM_SETTLE_SECONDS (float): How long a ping's connection is watched after its answer before it is returned to the pool, so a connection the server closes straight after answering never reaches an order.
        session (requests.Session): The session every request to this broker is sent through, so later requests reuse its open connection.
        adapter (IdleLimitedAdapter): The session's adapter, whose pools refuse connections idle longer than `MAXIMUM_IDLE_SECONDS`.
        origin_lock (threading.Lock): Guards `last_origin`.
        last_origin (str | None): The scheme and host of the latest request sent to this broker, such as `https://api.kite.trade/`.
        daily_count (DailyOrderCount | None): What counts every request sent to this broker against its daily cap, or None when no broker is capped.
    """

    BROKER_NAME = None
    IDENTIFIER_FIELD = 'order_symbol'
    PLACE_SETTINGS_FIELDS = []
    CANCEL_SETTINGS_FIELDS = []
    MODIFY_SETTINGS_FIELDS = []
    MODIFIABLE_FIELDS = []
    MODIFY_ORDER_TYPES = [
        'MARKET',
        'LIMIT',
        'SL',
        'SL-M',
    ]
    MARKETS = {}
    QUANTITY_UNITS = {}
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

    MAXIMUM_IDLE_SECONDS = 30.0
    WARM_URL = None
    WARM_INTERVAL_SECONDS = 20.0
    WARM_TIMEOUT_SECONDS = (
        3.05,
        5,
    )
    WARM_SETTLE_SECONDS = 1.0

    def __init__(self):
        """Builds the broker's order class with a session that has no connection open yet.

        The session's adapter is requests' default adapter except that its pools close a connection idle longer than `MAXIMUM_IDLE_SECONDS` instead of reusing it.
        For a broker whose certificate is deliberately not checked, urllib3's warning about that host is silenced, because a warmer would otherwise log it on every ping.

        Returns:
            None: This method returns nothing.
        """
        self.session = requests.Session()
        self.adapter = IdleLimitedAdapter(self.MAXIMUM_IDLE_SECONDS)
        self.session.mount('https://', self.adapter)
        self.session.mount('http://', self.adapter)
        self.origin_lock = threading.Lock()
        self.last_origin = None
        self.daily_count = None
        if not self.VERIFY_CERTIFICATE and self.WARM_URL is not None:
            host = urllib.parse.urlsplit(self.WARM_URL).hostname
            warnings.filterwarnings(
                'ignore',
                message=f'.*{re.escape(host)}.*',
                category=urllib3.exceptions.InsecureRequestWarning,
            )

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

    def decode_login(self, login_text):
        """Decodes this broker's login from Redis.

        Args:
            login_text (str | None): The login as Redis holds it.

        Returns:
            object: The decoded login, or None when there is none or it is not JSON.
        """
        if not login_text:
            return None
        try:
            return json.loads(login_text)
        except ValueError:
            return None

    def decode_settings(self, settings_text):
        """Decodes this broker's settings from Redis.

        Args:
            settings_text (str | None): The settings as Redis holds them.

        Returns:
            dict: The decoded settings, or an empty dictionary when there are none or they are not a JSON object.
        """
        if not settings_text:
            return {}
        try:
            settings = json.loads(settings_text)
        except ValueError:
            return {}
        if not isinstance(settings, dict):
            return {}
        return settings

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
        if not instrument.is_securities_market():
            quantity_unit = self.QUANTITY_UNITS.get(market)
            if quantity_unit is None:
                return f'does not know how it counts quantity in {" ".join(market)} orders'
        if not isinstance(handle, dict):
            return 'has no mapping for the instrument'
        if not handle.get(self.IDENTIFIER_FIELD):
            return f'its mapping carries no {self.IDENTIFIER_FIELD}'
        if not instrument.is_securities_market():
            if self.QUANTITY_UNITS[market] == 'broker_lot_size':
                if self.broker_lot_size(handle) is None:
                    return 'its mapping carries no whole lot size'
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
        triggered = order.order_type in OrderRequest.TRIGGERED_ORDER_TYPES
        if triggered and not self.TAKES_TRIGGERED_ORDERS:
            return f'takes no {order.order_type} orders'
        if order.after_market and not self.TAKES_AFTER_MARKET:
            return 'takes no after-market orders'
        return None

    def broker_lot_size(self, handle):
        """The broker's own lot size from its order handle, as a whole number.

        Args:
            handle (dict): The broker's order handle.

        Returns:
            int | None: The lot size, or None when it is missing, not positive or not whole.
        """
        try:
            lot_size = decimal.Decimal(str(handle.get('lot_size')))
        except decimal.InvalidOperation:
            return None
        if not lot_size.is_finite() or lot_size <= 0:
            return None
        if lot_size != lot_size.to_integral_value():
            return None
        return int(lot_size)

    def order_quantities(self, order, instrument, handle):
        """The quantity and disclosed quantity in the broker's own terms.

        For a securities market they are the order's own. For a currency or commodity market the order's quantities are whole lots of the instrument's trusted size, checked before the broker was chosen, and are converted by the broker's `QUANTITY_UNITS` entry for the market, which `place_skip_reason` has made sure exists.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            handle (dict): The broker's order handle for the instrument.

        Returns:
            tuple: `(quantity, disclosed_quantity)`, both ints.
        """
        quantity = self.broker_quantity(order.quantity, instrument, handle)
        disclosed_quantity = self.broker_quantity(
            order.disclosed_quantity,
            instrument,
            handle,
        )
        return quantity, disclosed_quantity

    def broker_quantity(self, units, instrument, handle):
        """One quantity in units, converted into the broker's own terms.

        For a securities market it is unchanged. For a currency or commodity market it must be a whole number of lots of the instrument's trusted size, which the caller has checked, and it is converted by the broker's `QUANTITY_UNITS` entry for the market, which the caller has made sure exists.

        Args:
            units (int): The quantity in units.
            instrument (Instrument): The tradeable instrument.
            handle (dict): The broker's order handle for the instrument.

        Returns:
            int: The quantity the broker's request carries.
        """
        if instrument.is_securities_market():
            return units
        units_per_lot = instrument.trusted_units_per_lot()
        lots = int(decimal.Decimal(units) / units_per_lot)
        quantity_unit = self.QUANTITY_UNITS[instrument.market()]
        if quantity_unit == 'lots':
            return lots
        if quantity_unit == 'broker_lot_size':
            return lots * self.broker_lot_size(handle)
        return units

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
        """Checks what the broker needs from its login beyond the access token, when cancelling or modifying an order.

        Args:
            login (dict): The broker's decoded login.

        Returns:
            str | None: The error message, or None.
        """
        del login
        return None

    def takes_modifications(self):
        """Whether the broker's modify request is built.

        Returns:
            bool: True when `MODIFIABLE_FIELDS` lists at least one field.
        """
        return len(self.MODIFIABLE_FIELDS) > 0

    def modify_problem(self, login, settings):
        """Decides whether a modification can be sent with the broker's login and settings.

        Args:
            login (object): The broker's decoded login, or None.
            settings (dict): The broker's decoded settings.

        Returns:
            str | None: The error message answered with HTTP 503, or None when the modification can be sent.
        """
        broker_name = self.BROKER_NAME
        if not isinstance(login, dict) or not login.get('access_token'):
            return f'{broker_name} has no login in Redis'
        login_problem = self.cancel_login_problem(login)
        if login_problem is not None:
            return login_problem
        missing = self.missing_settings(settings, self.MODIFY_SETTINGS_FIELDS)
        if missing:
            return (
                f'{broker_name} has no '
                + ', '.join(missing)
                + ' in its Redis settings'
            )
        return None

    def modify_field_problem(self, modify_request):
        """Decides whether the broker's modify request can change every field the caller gave.

        Args:
            modify_request (ModifyOrderRequest): The validated modification.

        Returns:
            str | None: The error message answered with HTTP 400, or None when every field can be changed.
        """
        for field_name in modify_request.changed_fields:
            if field_name not in self.MODIFIABLE_FIELDS:
                return f'{self.BROKER_NAME} cannot change {field_name} on an order'
        order_type = modify_request.order_type
        if order_type is None:
            return None
        triggered = order_type in OrderRequest.TRIGGERED_ORDER_TYPES
        if triggered and not self.TAKES_TRIGGERED_ORDERS:
            return f'{self.BROKER_NAME} takes no {order_type} orders'
        if order_type not in self.MODIFY_ORDER_TYPES:
            return f'{self.BROKER_NAME} cannot change an order to {order_type}'
        return None

    def takes_only_securities(self):
        """Whether every market the broker takes is a securities market, where a quantity in units is already in the broker's own terms.

        Returns:
            bool: True when no currency or commodity market is listed in `MARKETS`.
        """
        for market in self.MARKETS:
            if market[1] != 'securities':
                return False
        return True

    def stored_exchange_matches(self, instrument, stored_exchange):
        """Whether an instrument's market fits the exchange code the broker's order scripts stored on an order.

        The stored code is the one the broker's order book spells, which for most brokers is the code `MARKETS` lists for the market.

        Args:
            instrument (Instrument): A tradeable instrument whose market is in `MARKETS`.
            stored_exchange (str | None): The stored normalized order's `exchange`.

        Returns:
            bool: True when the codes agree, ignoring case, or when no code is stored.
        """
        if stored_exchange is None:
            return True
        market_code = str(self.MARKETS[instrument.market()])
        return stored_exchange.upper() == market_code.upper()

    def quantity_conversion_problem(self, instrument, handle):
        """Decides whether a quantity in units can be converted into the broker's own terms for an instrument.

        Args:
            instrument (Instrument): The tradeable instrument.
            handle (object): The broker's order handle for the instrument, or None.

        Returns:
            str | None: The error message answered with HTTP 503, or None when the quantity can be converted.
        """
        if instrument.is_securities_market():
            return None
        market = instrument.market()
        quantity_unit = self.QUANTITY_UNITS.get(market)
        if quantity_unit is None:
            return f'{self.BROKER_NAME} does not know how it counts quantity in {" ".join(market)} orders'
        if quantity_unit == 'broker_lot_size':
            if not isinstance(handle, dict):
                return f"{self.BROKER_NAME}'s mapping carries no whole lot size for the instrument"
            if self.broker_lot_size(handle) is None:
                return f"{self.BROKER_NAME}'s mapping carries no whole lot size for the instrument"
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

    def stored_value(self, value, field_name):
        """A value of the order after the change that the broker's modify request sends, which Redis may not hold.

        Args:
            value (object): The value from the `OrderModification`.
            field_name (str): The field's name, for the error message.

        Returns:
            object: The value.

        Raises:
            OrderNotReadyError: When the value is None.
        """
        if value is None:
            message = f"Redis does not hold this {self.BROKER_NAME} order's {field_name} yet, so try again after the broker's next order book poll"
            raise OrderNotReadyError(message)
        return value

    def build_modify_request(
        self,
        order_id,
        stored_order,
        modification,
        login,
        settings,
    ):
        """Builds the broker's modify request.

        Args:
            order_id (str): The broker's order id.
            stored_order (StoredOrder): The order as the broker's order scripts keep it in Redis.
            modification (OrderModification): The order after the change, with quantities in the broker's own terms.
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
        self.remember_origin(broker_request.url)
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
        self.count_message(answer)
        if response is not None:
            answer.status_code = response.status_code
            try:
                answer.response_body = response.json()
            except ValueError:
                answer.response_body = response.text[:300]
        return answer

    def count_message(self, answer):
        """Counts one request against the broker's daily cap, unless it never left the machine.

        Args:
            answer (BrokerAnswer): The answer, whose outcome is already `rejected` when the connection could not be made.

        Returns:
            None: This method returns nothing.
        """
        if self.daily_count is None:
            return
        if answer.outcome == 'rejected' and answer.status_code is None:
            return
        self.daily_count.count_sent(self.BROKER_NAME)

    def remember_origin(self, url):
        """Remembers the scheme and host a request is sent to, so warming pings reach the same connection pool.

        Args:
            url (str): The request's URL.

        Returns:
            None: This method returns nothing.
        """
        parts = urllib.parse.urlsplit(url)
        with self.origin_lock:
            self.last_origin = f'{parts.scheme}://{parts.netloc}/'

    def warm_url(self):
        """The URL a warming ping is sent to: the host of the latest request, or `WARM_URL` before there has been one.

        Returns:
            str | None: The URL, or None when there is nothing to warm.
        """
        with self.origin_lock:
            last_origin = self.last_origin
        if last_origin is not None:
            return last_origin
        return self.WARM_URL

    def warm_connection(self):
        """Sends one `HEAD` request with no credentials to the broker's host, so a connection in the order pool is freshly used.

        The ping goes straight to the session's adapter, so it shares the order requests' connection pool but never reads or writes the session's cookies or headers. After the answer, the connection is watched for `WARM_SETTLE_SECONDS`; it is returned to the pool only if the server has not closed it or sent anything in that time, and otherwise it is closed.

        Returns:
            str: `kept` when a healthy connection went back to the pool, `discarded` when the connection was closed instead, or `skipped` when there is no URL to warm.

        Raises:
            requests.exceptions.RequestException: When the ping fails; the pool has already closed that connection.
        """
        url = self.warm_url()
        if url is None:
            return 'skipped'
        prepared_request = requests.Request('HEAD', url).prepare()
        response = self.adapter.send(
            prepared_request,
            stream=True,
            timeout=self.WARM_TIMEOUT_SECONDS,
            verify=self.VERIFY_CERTIFICATE,
        )
        raw_response = response.raw
        connection = raw_response.connection
        healthy = False
        try:
            if connection is not None and connection.sock is not None:
                closed_or_talking = urllib3.util.wait.wait_for_read(
                    connection.sock,
                    timeout=self.WARM_SETTLE_SECONDS,
                )
                healthy = not closed_or_talking
            if healthy:
                raw_response.read()
        finally:
            if not healthy and connection is not None:
                connection.close()
            raw_response.release_conn()
        if healthy:
            return 'kept'
        return 'discarded'

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
        self.decide_instruction_outcome(answer)
        return answer

    def send_modify(self, broker_request):
        """Sends a modify request and decides whether the broker took it, by the rules a cancel is decided by.

        Args:
            broker_request (BrokerRequest): The request.

        Returns:
            BrokerAnswer: The answer.
        """
        answer = self.send(broker_request)
        self.decide_instruction_outcome(answer)
        return answer

    def decide_instruction_outcome(self, answer):
        """Decides whether the broker took an instruction about an existing order, a cancel or a modification.

        An error status below 500 is `rejected` and a server error is `unknown`. A success status is `rejected` when its body carries a refusal and `accepted` otherwise, which means the broker took the instruction, not that the exchange has acted on it. An answer with no status, after a network error, keeps the outcome `send` gave it.

        Args:
            answer (BrokerAnswer): The answer, whose `outcome` and `status_message` are set.

        Returns:
            None: This method returns nothing.
        """
        if answer.status_code is None:
            return

        if answer.status_code >= 300:
            answer.status_message = self.error_message(answer)
            if answer.status_code < 500:
                answer.outcome = 'rejected'
            else:
                answer.outcome = 'unknown'
            return

        refusal = self.read_refusal(answer.response_fields())
        if refusal is not None:
            answer.outcome = 'rejected'
            answer.status_message = str(refusal)[:300]
        else:
            answer.outcome = 'accepted'
