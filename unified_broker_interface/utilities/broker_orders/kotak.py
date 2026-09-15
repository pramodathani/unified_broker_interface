"""How Kotak Neo's trade API takes, modifies and cancels orders."""

import json

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    OrderNotReadyError,
)


class KotakOrders(BrokerOrders):
    """Kotak's order requests, sent as a `jData` form field to the host its login names.

    Kotak's host comes from its login and differs between accounts and logins, so `WARM_URL` is None: a warmer pings nothing until the first Kotak request of the worker has named the host, and then keeps that host's connection warm.

    Attributes:
        DEFAULT_BASE_URL (str): The host used when the stored login names none.
        ORDER_TYPE_CODES (dict): The shared order types to Kotak's.
        SIDE_CODES (dict): The shared transaction types to Kotak's.
    """

    BROKER_NAME = 'kotak'
    IDENTIFIER_FIELD = 'order_symbol'
    PLACE_SETTINGS_FIELDS = []
    CANCEL_SETTINGS_FIELDS = []
    MODIFY_SETTINGS_FIELDS = []
    MODIFIABLE_FIELDS = [
        'quantity',
        'disclosed_quantity',
        'price',
        'trigger_price',
        'order_type',
        'validity',
    ]
    MAXIMUM_IDLE_SECONDS = 300.0
    WARM_URL = None
    WARM_INTERVAL_SECONDS = 60.0
    MARKETS = {
        ('nse', 'securities', 'cash'): 'nse_cm',
        ('bse', 'securities', 'cash'): 'bse_cm',
        ('nse', 'securities', 'derivative'): 'nse_fo',
        ('bse', 'securities', 'derivative'): 'bse_fo',
        ('mcx', 'commodity', 'derivative'): 'mcx_fo',
    }
    QUANTITY_UNITS = {
        ('mcx', 'commodity', 'derivative'): 'broker_lot_size',
    }
    DEFAULT_BASE_URL = 'https://gw-napi.kotaksecurities.com'
    ORDER_TYPE_CODES = {
        'MARKET': 'MKT',
        'LIMIT': 'L',
        'SL': 'SL',
        'SL-M': 'SL-M',
    }
    SIDE_CODES = {
        'BUY': 'B',
        'SELL': 'S',
    }

    def login_skip_reason(self, login):
        """Passes Kotak over when its login carries no `sid`.

        Args:
            login (dict): Kotak's decoded login.

        Returns:
            str | None: The reason, or None.
        """
        if not login.get('sid'):
            return 'its login in Redis carries no sid'
        return None

    def cancel_login_problem(self, login):
        """Refuses a cancel when Kotak's login carries no `sid`.

        Args:
            login (dict): Kotak's decoded login.

        Returns:
            str | None: The error message, or None.
        """
        if not login.get('sid'):
            return 'kotak has no sid in its login in Redis'
        return None

    def base_url(self, login):
        """The host from the stored login, normalized the way `KotakAPI.base_url` does it.

        Args:
            login (dict): Kotak's decoded login.

        Returns:
            str: The base URL with a scheme and no trailing slash.
        """
        base_url = str(login.get('base_url') or '').strip()
        base_url = base_url.rstrip('/')
        if not base_url or base_url == 'None':
            return self.DEFAULT_BASE_URL
        if not base_url.startswith((
            'http://',
            'https://',
        )):
            return f'https://{base_url}'
        return base_url

    def headers(self, login):
        """Builds Kotak's session headers.

        Args:
            login (dict): Kotak's decoded login.

        Returns:
            dict: The headers.
        """
        return {
            'neo-fin-key': 'neotradeapi',
            'Auth': str(login.get('access_token')),
            'Sid': str(login.get('sid')),
        }

    def build_place_request(self, order, instrument, handle, login, settings):
        """Builds `POST {base_url}/quick/order/rule/ms/place`.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            handle (dict): Kotak's order handle for the instrument.
            login (dict): Kotak's decoded login.
            settings (dict): Kotak's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        after_market_text = 'NO'
        if order.after_market:
            after_market_text = 'YES'
        kotak_fields = {
            'es': self.MARKETS[instrument.market()],
            'ts': handle.get('order_symbol'),
            'qt': str(order.quantity),
            'pr': order.price_text,
            'tp': order.trigger_price_text,
            'dq': str(order.disclosed_quantity),
            'pc': order.product,
            'tt': self.SIDE_CODES[order.transaction_type],
            'pt': self.ORDER_TYPE_CODES[order.order_type],
            'rt': order.validity,
            'mp': '0',
            'pf': 'N',
            'am': after_market_text,
        }
        if order.tag:
            kotak_fields['rm'] = order.tag
        form = {
            'jData': json.dumps(kotak_fields),
        }
        return BrokerRequest(
            'POST',
            f'{self.base_url(login)}/quick/order/rule/ms/place',
            self.headers(login),
            data=form,
            shown_form=form,
            tag=order.tag,
        )

    def build_cancel_request(self, order_id, stored_order, login, settings):
        """Builds `POST {base_url}/quick/order/cancel`, with `am` set to `YES` when Kotak's order book marks the order `ordGenTp` `AMO`, because Kotak refuses a cancel of an after-market order sent with `NO`.

        Args:
            order_id (str): Kotak's order id.
            stored_order (StoredOrder): The order as Redis holds it.
            login (dict): Kotak's decoded login.
            settings (dict): Kotak's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        after_market_text = 'NO'
        if str(stored_order.data.get('ordGenTp') or '').upper() == 'AMO':
            after_market_text = 'YES'
        kotak_fields = {
            'on': order_id,
            'am': after_market_text,
        }
        form = {
            'jData': json.dumps(kotak_fields),
        }
        return BrokerRequest(
            'POST',
            f'{self.base_url(login)}/quick/order/cancel',
            self.headers(login),
            data=form,
            shown_form=form,
        )

    def build_modify_request(
        self,
        order_id,
        stored_order,
        modification,
        login,
        settings,
    ):
        """Builds `POST {base_url}/quick/order/vr/modify` with the whole order after the change, in the keys Kotak's modification takes.

        A modification names validity `vd` where a placement names it `rt`, and restates the instrument token, exchange segment, trading symbol, side and product. The trading symbol is read from Kotak's own `trdSym`, because the normalized symbol falls back to the underlying's name when Kotak sends none.

        Args:
            order_id (str): Kotak's order id.
            stored_order (StoredOrder): The order as Redis holds it.
            modification (OrderModification): The order after the change.
            login (dict): Kotak's decoded login.
            settings (dict): Kotak's decoded settings.

        Returns:
            BrokerRequest: The request.

        Raises:
            OrderNotReadyError: When Redis does not hold the order's token, exchange segment, trading symbol, side, product or validity.
        """
        trading_symbol = stored_order.data.get('trdSym')
        missing = (
            modification.instrument_token is None
            or modification.exchange is None
            or not trading_symbol
        )
        if missing:
            message = (
                "Redis does not hold this Kotak order's token, exchange segment and trading symbol yet, so try again after Kotak's next order book poll"
            )
            raise OrderNotReadyError(message)
        transaction_type = self.stored_value(
            modification.transaction_type,
            'transaction_type',
        )
        kotak_fields = {
            'no': order_id,
            'tk': modification.instrument_token,
            'es': modification.exchange,
            'ts': str(trading_symbol),
            'tt': self.SIDE_CODES[transaction_type],
            'pc': self.stored_value(modification.product, 'product'),
            'pt': self.ORDER_TYPE_CODES[modification.order_type],
            'qt': str(modification.quantity),
            'pr': modification.price_text,
            'tp': modification.trigger_price_text,
            'dq': str(modification.disclosed_quantity),
            'vd': self.stored_value(modification.validity, 'validity'),
            'dd': 'NA',
            'mp': '0',
        }
        form = {
            'jData': json.dumps(kotak_fields),
        }
        return BrokerRequest(
            'POST',
            f'{self.base_url(login)}/quick/order/vr/modify',
            self.headers(login),
            data=form,
            shown_form=form,
        )

    def read_order_id(self, response_fields):
        """Reads `nOrdNo`.

        Args:
            response_fields (dict): Kotak's JSON body.

        Returns:
            object: The order id, or None.
        """
        return response_fields.get('nOrdNo')

    def read_refusal(self, response_fields):
        """Reads a refusal from a `stat` of `Not_Ok` or any `errMsg`.

        Args:
            response_fields (dict): Kotak's JSON body.

        Returns:
            object: The refusal message, or None.
        """
        kotak_refused = response_fields.get('stat') == 'Not_Ok'
        if not kotak_refused and not response_fields.get('errMsg'):
            return None
        refusal = response_fields.get('errMsg')
        if not refusal:
            refusal = 'the broker refused the request'
        return refusal
