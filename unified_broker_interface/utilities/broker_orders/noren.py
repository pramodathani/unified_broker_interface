"""How the Noren platform, which Flattrade and Shoonya run, takes, modifies and cancels orders."""

import datetime
import json
import zoneinfo

import requests

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    OrderNotReadyError,
)


class NorenOrders(BrokerOrders):
    """A Noren broker's order requests, sent as a `jData=...&jKey=...` body.

    A subclass sets `BROKER_NAME`, `BASE_URL`, `ACCOUNT_SETTINGS_FIELD` and the three settings lists.

    After a place-order request whose connection was reset, `find_placed_order` reads Noren's `OrderBook` on a new connection, so the base class can tell an order that arrived from one that never did.

    Attributes:
        BASE_URL (str): The API's base URL.
        ACCOUNT_SETTINGS_FIELD (str): The settings field holding the account id sent as `uid` and `actid`.
        ORDER_TYPE_CODES (dict): The shared order types to Noren's.
        PRODUCT_CODES (dict): The shared products to Noren's.
        SIDE_CODES (dict): The shared transaction types to Noren's.
        INDIA (zoneinfo.ZoneInfo): India's time zone, which Noren's order times are in.
        ORDER_TIME_FORMATS (list): The two forms Noren writes an order time in.
        LOOKUP_EARLY_SECONDS (float): How long before the request was sent an order's time may be and still be the request's, allowing for the broker's clock running behind.
        LOOKUP_MATCHED_FIELDS (list): The request fields an order in the book must repeat to be the request's.
        NO_DATA_MARKER (str): The text in Noren's refusal when the book is simply empty.
    """

    BASE_URL = None
    ACCOUNT_SETTINGS_FIELD = None
    IDENTIFIER_FIELD = 'order_symbol'
    MODIFIABLE_FIELDS = [
        'quantity',
        'disclosed_quantity',
        'price',
        'trigger_price',
        'order_type',
        'validity',
    ]
    MODIFY_ORDER_TYPES = [
        'LIMIT',
        'SL',
    ]
    MARKETS = {
        ('nse', 'securities', 'cash'): 'NSE',
        ('bse', 'securities', 'cash'): 'BSE',
        ('nse', 'securities', 'derivative'): 'NFO',
        ('bse', 'securities', 'derivative'): 'BFO',
        ('mcx', 'commodity', 'derivative'): 'MCX',
        ('nse', 'currency', 'derivative'): 'CDS',
    }
    QUANTITY_UNITS = {
        ('mcx', 'commodity', 'derivative'): 'broker_lot_size',
        ('nse', 'currency', 'derivative'): 'broker_lot_size',
    }
    ORDER_TYPE_CODES = {
        'MARKET': 'MKT',
        'LIMIT': 'LMT',
        'SL': 'SL-LMT',
        'SL-M': 'SL-MKT',
    }
    PRODUCT_CODES = {
        'CNC': 'C',
        'MIS': 'I',
        'NRML': 'M',
    }
    SIDE_CODES = {
        'BUY': 'B',
        'SELL': 'S',
    }
    INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')
    ORDER_TIME_FORMATS = [
        '%H:%M:%S %d-%m-%Y',
        '%d-%m-%Y %H:%M:%S',
    ]
    LOOKUP_EARLY_SECONDS = 5.0
    LOOKUP_MATCHED_FIELDS = [
        'exch',
        'tsym',
        'trantype',
        'prd',
        'prctyp',
    ]
    NO_DATA_MARKER = 'no data'

    def encoded_body(self, noren_fields, login):
        """Encodes the fields as Noren's body, with `&` in the JSON escaped so a symbol such as `M&M` does not end the field early.

        Args:
            noren_fields (dict): The `jData` fields.
            login (dict): The broker's decoded login.

        Returns:
            str: The body.
        """
        escaped_fields = json.dumps(noren_fields).replace('&', '\\u0026')
        login_token = str(login.get('access_token'))
        return f'jData={escaped_fields}&jKey={login_token}'

    def build_place_request(self, order, instrument, handle, login, settings):
        """Builds `POST {BASE_URL}/PlaceOrder`.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            handle (dict): The broker's order handle for the instrument.
            login (dict): The broker's decoded login.
            settings (dict): The broker's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        account_identifier = str(settings[self.ACCOUNT_SETTINGS_FIELD])
        after_market_text = 'NO'
        if order.after_market:
            after_market_text = 'YES'
        noren_fields = {
            'uid': account_identifier,
            'actid': account_identifier,
            'exch': self.MARKETS[instrument.market()],
            'tsym': handle.get('order_symbol'),
            'qty': str(order.quantity),
            'prc': order.price_text,
            'trgprc': order.trigger_price_text,
            'dscqty': str(order.disclosed_quantity),
            'prd': self.PRODUCT_CODES[order.product],
            'trantype': self.SIDE_CODES[order.transaction_type],
            'prctyp': self.ORDER_TYPE_CODES[order.order_type],
            'ret': order.validity,
            'ordersource': 'API',
            'amo': after_market_text,
        }
        if order.tag:
            noren_fields['remarks'] = order.tag
        return BrokerRequest(
            'POST',
            f'{self.BASE_URL}/PlaceOrder',
            {},
            data=self.encoded_body(noren_fields, login),
            shown_form=noren_fields,
            tag=order.tag,
        )

    def build_cancel_request(self, order_id, stored_order, login, settings):
        """Builds `POST {BASE_URL}/CancelOrder`.

        Args:
            order_id (str): The broker's order id.
            stored_order (StoredOrder): The order as Redis holds it.
            login (dict): The broker's decoded login.
            settings (dict): The broker's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        noren_fields = {
            'uid': str(settings[self.ACCOUNT_SETTINGS_FIELD]),
            'norenordno': order_id,
        }
        return BrokerRequest(
            'POST',
            f'{self.BASE_URL}/CancelOrder',
            {},
            data=self.encoded_body(noren_fields, login),
            shown_form=noren_fields,
        )

    def build_modify_request(
        self,
        order_id,
        stored_order,
        modification,
        login,
        settings,
    ):
        """Builds `POST {BASE_URL}/ModifyOrder` with the exchange and trading symbol the order was placed with.

        Noren takes the new total quantity. The trigger price is sent only for a stop-loss order, because a zero trigger price on a limit order is refused, and the disclosed quantity only when the caller changed it.

        Args:
            order_id (str): The broker's order id.
            stored_order (StoredOrder): The order as Redis holds it.
            modification (OrderModification): The order after the change.
            login (dict): The broker's decoded login.
            settings (dict): The broker's decoded settings.

        Returns:
            BrokerRequest: The request.

        Raises:
            OrderNotReadyError: When Redis does not hold the order's exchange, trading symbol or validity.
        """
        if modification.exchange is None or modification.tradingsymbol is None:
            message = (
                "Redis does not hold this order's exchange and trading symbol yet, so try again after the broker's next order book poll"
            )
            raise OrderNotReadyError(message)
        account_identifier = str(settings[self.ACCOUNT_SETTINGS_FIELD])
        noren_fields = {
            'ordersource': 'API',
            'uid': account_identifier,
            'actid': account_identifier,
            'norenordno': order_id,
            'exch': modification.exchange,
            'tsym': modification.tradingsymbol,
            'qty': str(modification.quantity),
            'prctyp': self.ORDER_TYPE_CODES[modification.order_type],
            'prc': modification.price_text,
            'ret': self.stored_value(modification.validity, 'validity'),
        }
        if modification.trigger_price is not None:
            noren_fields['trgprc'] = modification.trigger_price_text
        if modification.changes('disclosed_quantity'):
            noren_fields['dscqty'] = str(modification.disclosed_quantity)
        return BrokerRequest(
            'POST',
            f'{self.BASE_URL}/ModifyOrder',
            {},
            data=self.encoded_body(noren_fields, login),
            shown_form=noren_fields,
        )

    def read_order_id(self, response_fields):
        """Reads `norenordno`, or `result` when there is none.

        Args:
            response_fields (dict): Noren's JSON body.

        Returns:
            object: The order id, or None.
        """
        order_id = response_fields.get('norenordno')
        if not order_id:
            order_id = response_fields.get('result')
        return order_id

    def read_refusal(self, response_fields):
        """Reads a refusal from a `stat` other than `Ok`.

        Args:
            response_fields (dict): Noren's JSON body.

        Returns:
            object: The refusal message, or None.
        """
        stat = str(response_fields.get('stat', ''))
        if stat.lower() == 'ok':
            return None
        refusal = response_fields.get('emsg')
        if not refusal:
            refusal = 'the broker refused the request'
        return refusal

    def order_book_request(self, broker_request):
        """Builds `POST {BASE_URL}/OrderBook` with the same account and login as a place-order request.

        Args:
            broker_request (BrokerRequest): The place-order request, whose body ends with `&jKey=<token>`.

        Returns:
            BrokerRequest | None: The request, or None when the place-order request carries no account or token.
        """
        fields = broker_request.shown_form or {}
        account_identifier = fields.get('uid')
        body = broker_request.data
        if not account_identifier or not isinstance(body, str) or '&jKey=' not in body:
            return None
        login_token = body.rsplit('&jKey=', 1)[1]
        book_fields = {
            'uid': account_identifier,
        }
        return BrokerRequest(
            'POST',
            f'{self.BASE_URL}/OrderBook',
            {},
            data=self.encoded_body(book_fields, {'access_token': login_token}),
            shown_form=book_fields,
        )

    def order_time(self, text):
        """Reads an order time as Noren writes it.

        Args:
            text (object): Noren's `norentm`, in either of `ORDER_TIME_FORMATS`.

        Returns:
            float | None: The time as seconds since the epoch, or None when it cannot be read.
        """
        for time_format in self.ORDER_TIME_FORMATS:
            try:
                moment = datetime.datetime.strptime(str(text).strip(), time_format)
            except ValueError:
                continue
            return moment.replace(tzinfo=self.INDIA).timestamp()
        return None

    def same_number(self, first, second):
        """Whether two of Noren's numbers are equal, written as text or as numbers.

        Args:
            first (object): One number.
            second (object): The other.

        Returns:
            bool: True when both read as the same number, or are both empty.
        """
        if first in (None, '') and second in (None, ''):
            return True
        try:
            return float(first) == float(second)
        except (TypeError, ValueError):
            return False

    def matches_request(self, row, fields, sent_at_epoch):
        """Whether one order in Noren's book is the order a place-order request asked for.

        It must repeat the exchange, symbol, side, product and order type, the quantity and the price, the trigger price when one was sent, and the remarks when they were sent, and must have reached the broker no earlier than `LOOKUP_EARLY_SECONDS` before the request was sent.

        Args:
            row (dict): One order in Noren's book.
            fields (dict): The request's `jData` fields.
            sent_at_epoch (float): When the request was sent, as seconds since the epoch.

        Returns:
            bool: True when every field matches.
        """
        for name in self.LOOKUP_MATCHED_FIELDS:
            if str(row.get(name, '')) != str(fields.get(name, '')):
                return False
        if not self.same_number(row.get('qty'), fields.get('qty')):
            return False
        if fields.get('prctyp') in ('LMT', 'SL-LMT'):
            if not self.same_number(row.get('prc'), fields.get('prc')):
                return False
        if fields.get('trgprc') not in (None, ''):
            if not self.same_number(row.get('trgprc'), fields.get('trgprc')):
                return False
        if fields.get('remarks'):
            if str(row.get('remarks', '')) != str(fields.get('remarks')):
                return False
        order_epoch = self.order_time(row.get('norentm'))
        if order_epoch is None:
            return False
        return order_epoch >= sent_at_epoch - self.LOOKUP_EARLY_SECONDS

    def find_placed_order(self, broker_request, sent_at_epoch):
        """Reads Noren's order book on a new connection and looks for the order a reset place-order request carried.

        Args:
            broker_request (BrokerRequest): The place-order request that was sent.
            sent_at_epoch (float): When it was sent, as seconds since the epoch.

        Returns:
            tuple: `(state, order_id, message)`, where state is `found` with Noren's order number when exactly one order matches, `absent` when the book was read and none does, or `cannot_tell` when the book could not be read or several orders match.
        """
        book_request = self.order_book_request(broker_request)
        if book_request is None:
            return 'cannot_tell', None, 'the request carries no account or login to read the order book with'
        with requests.Session() as session:
            book_answer = self.send(book_request, session)
        body = book_answer.response_body
        if book_answer.status_code is None:
            return 'cannot_tell', None, f'the order book could not be read either: {book_answer.status_message}'
        if isinstance(body, dict):
            message = str(body.get('emsg') or body)
            if self.NO_DATA_MARKER in message.lower():
                return 'absent', None, 'the order book is empty'
            return 'cannot_tell', None, f'the order book could not be read: {message[:200]}'
        if not isinstance(body, list):
            return 'cannot_tell', None, f'the order book came back without a list: {str(body)[:200]}'
        fields = broker_request.shown_form or {}
        matching_numbers = []
        for row in body:
            if isinstance(row, dict) and self.matches_request(row, fields, sent_at_epoch):
                matching_numbers.append(str(row.get('norenordno')))
        if len(matching_numbers) == 1:
            return 'found', matching_numbers[0], 'one order in the book matches'
        if not matching_numbers:
            return 'absent', None, 'no order in the book matches'
        return 'cannot_tell', None, f'{len(matching_numbers)} orders in the book match, so it is not known which, if any, is this one'

    def is_settled_refusal(self, error_code):
        """Whether the error code is Noren's `Not_Ok`.

        Args:
            error_code (str): The error code, which is Noren's `stat`.

        Returns:
            bool: True for a settled refusal.
        """
        return error_code == 'Not_Ok'
