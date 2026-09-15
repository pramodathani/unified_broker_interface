"""How the Noren platform, which Flattrade and Shoonya run, takes and cancels orders."""

import json

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)


class NorenOrders(BrokerOrders):
    """A Noren broker's order requests, sent as a `jData=...&jKey=...` body.

    A subclass sets `BROKER_NAME`, `BASE_URL`, `ACCOUNT_SETTINGS_FIELD` and the two settings lists.

    Attributes:
        BASE_URL (str): The API's base URL.
        ACCOUNT_SETTINGS_FIELD (str): The settings field holding the account id sent as `uid` and `actid`.
        ORDER_TYPE_CODES (dict): The shared order types to Noren's.
        PRODUCT_CODES (dict): The shared products to Noren's.
        SIDE_CODES (dict): The shared transaction types to Noren's.
    """

    BASE_URL = None
    ACCOUNT_SETTINGS_FIELD = None
    IDENTIFIER_FIELD = 'order_symbol'
    MARKETS = {
        ('nse', 'securities', 'cash'): 'NSE',
        ('bse', 'securities', 'cash'): 'BSE',
        ('nse', 'securities', 'derivative'): 'NFO',
        ('bse', 'securities', 'derivative'): 'BFO',
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

    def is_settled_refusal(self, error_code):
        """Whether the error code is Noren's `Not_Ok`.

        Args:
            error_code (str): The error code, which is Noren's `stat`.

        Returns:
            bool: True for a settled refusal.
        """
        return error_code == 'Not_Ok'
