"""How Fyers' v3 API takes, modifies and cancels orders."""

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)


class FyersOrders(BrokerOrders):
    """Fyers' order requests, sent as JSON to `api-t1.fyers.in`.

    Attributes:
        ORDER_TYPE_CODES (dict): The shared order types to Fyers' numeric codes.
        SIDE_CODES (dict): The shared transaction types to Fyers' numeric sides.
        PRODUCT_CODES (dict): The shared products to Fyers'.
    """

    BROKER_NAME = 'fyers'
    IDENTIFIER_FIELD = 'order_symbol'
    PLACE_SETTINGS_FIELDS = [
        'app_id',
    ]
    CANCEL_SETTINGS_FIELDS = [
        'app_id',
    ]
    MODIFY_SETTINGS_FIELDS = [
        'app_id',
    ]
    MODIFIABLE_FIELDS = [
        'quantity',
        'disclosed_quantity',
        'price',
        'trigger_price',
        'order_type',
    ]
    MAXIMUM_IDLE_SECONDS = 300.0
    WARM_URL = 'https://api-t1.fyers.in/'
    WARM_INTERVAL_SECONDS = 60.0
    MARKETS = {
        ('nse', 'securities', 'cash'): 'NSE',
        ('bse', 'securities', 'cash'): 'BSE',
        ('nse', 'securities', 'derivative'): 'NSE',
        ('bse', 'securities', 'derivative'): 'BSE',
        ('mcx', 'commodity', 'derivative'): 'MCX',
        ('nse', 'currency', 'derivative'): 'NSE',
    }
    QUANTITY_UNITS = {
        ('mcx', 'commodity', 'derivative'): 'broker_lot_size',
        ('nse', 'currency', 'derivative'): 'broker_lot_size',
    }
    ORDER_TYPE_CODES = {
        'LIMIT': 1,
        'MARKET': 2,
        'SL-M': 3,
        'SL': 4,
    }
    SIDE_CODES = {
        'BUY': 1,
        'SELL': -1,
    }
    PRODUCT_CODES = {
        'CNC': 'CNC',
        'MIS': 'INTRADAY',
        'NRML': 'MARGIN',
    }

    def headers(self, login, settings):
        """Builds Fyers' session headers.

        Args:
            login (dict): Fyers' decoded login.
            settings (dict): Fyers' decoded settings.

        Returns:
            dict: The headers.
        """
        login_token = str(login.get('access_token'))
        return {
            'Authorization': f'{settings["app_id"]}:{login_token}',
        }

    def build_place_request(self, order, instrument, handle, login, settings):
        """Builds `POST /api/v3/orders/sync`; the exchange is part of Fyers' symbol, so the market's code is not sent.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            handle (dict): Fyers' order handle for the instrument.
            login (dict): Fyers' decoded login.
            settings (dict): Fyers' decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        del instrument
        json_body = {
            'symbol': handle.get('order_symbol'),
            'qty': order.quantity,
            'type': self.ORDER_TYPE_CODES[order.order_type],
            'side': self.SIDE_CODES[order.transaction_type],
            'productType': self.PRODUCT_CODES[order.product],
            'limitPrice': order.price_number,
            'stopPrice': order.trigger_price_number,
            'validity': order.validity,
            'disclosedQty': order.disclosed_quantity,
            'offlineOrder': order.after_market,
        }
        if order.tag:
            json_body['orderTag'] = order.tag
        return BrokerRequest(
            'POST',
            'https://api-t1.fyers.in/api/v3/orders/sync',
            self.headers(login, settings),
            json_body=json_body,
            tag=order.tag,
        )

    def build_cancel_request(self, order_id, stored_order, login, settings):
        """Builds `DELETE /api/v3/orders/sync` with the order id in the JSON body.

        Args:
            order_id (str): Fyers' order id.
            stored_order (StoredOrder): The order as Redis holds it.
            login (dict): Fyers' decoded login.
            settings (dict): Fyers' decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        return BrokerRequest(
            'DELETE',
            'https://api-t1.fyers.in/api/v3/orders/sync',
            self.headers(login, settings),
            json_body={
                'id': order_id,
            },
        )

    def stored_exchange_matches(self, instrument, stored_exchange):
        """Whether an instrument's exchange is the one Fyers's order scripts stored, which is the bare exchange, such as `NSE`, rather than a market code.

        Args:
            instrument (Instrument): A tradeable instrument whose market is in `MARKETS`.
            stored_exchange (str | None): The stored normalized order's `exchange`.

        Returns:
            bool: True when the exchanges agree, ignoring case, or when no exchange is stored.
        """
        if stored_exchange is None:
            return True
        return stored_exchange.upper() == instrument.exchange.upper()

    def build_modify_request(
        self,
        order_id,
        stored_order,
        modification,
        login,
        settings,
    ):
        """Builds `PATCH /api/v3/orders/sync` with the order id in the JSON body.

        Fyers keeps the original value of every field a modification leaves out, except the order type, which it requires every time. A limit price or stop price is sent whenever the order type after the change takes one, and a quantity or disclosed quantity only when the caller changed it, because whether Fyers reads the quantity as the total or the remaining quantity is not confirmed. Fyers has no field for validity.

        Args:
            order_id (str): Fyers' order id.
            stored_order (StoredOrder): The order as Redis holds it.
            modification (OrderModification): The order after the change.
            login (dict): Fyers' decoded login.
            settings (dict): Fyers' decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        json_body = {
            'id': order_id,
            'type': self.ORDER_TYPE_CODES[modification.order_type],
        }
        if modification.price is not None:
            json_body['limitPrice'] = modification.price_number
        if modification.trigger_price is not None:
            json_body['stopPrice'] = modification.trigger_price_number
        if modification.changes('quantity'):
            json_body['qty'] = modification.quantity
        if modification.changes('disclosed_quantity'):
            json_body['disclosedQty'] = modification.disclosed_quantity
        return BrokerRequest(
            'PATCH',
            'https://api-t1.fyers.in/api/v3/orders/sync',
            self.headers(login, settings),
            json_body=json_body,
        )

    def read_order_id(self, response_fields):
        """Reads `id`.

        Args:
            response_fields (dict): Fyers' JSON body.

        Returns:
            object: The order id, or None.
        """
        return response_fields.get('id')

    def read_refusal(self, response_fields):
        """Reads a refusal from an `s` other than `ok`.

        Args:
            response_fields (dict): Fyers' JSON body.

        Returns:
            object: The refusal message, or None.
        """
        fyers_state = response_fields.get('s')
        if fyers_state is None or fyers_state == 'ok':
            return None
        refusal = response_fields.get('message')
        if not refusal:
            refusal = f's {fyers_state}'
        return refusal
