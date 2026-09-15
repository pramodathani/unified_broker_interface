"""How Stoxkart's open API takes, modifies and cancels orders."""

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    OrderNotReadyError,
)


class StoxkartOrders(BrokerOrders):
    """Stoxkart's order requests, sent as JSON to `openapi.stoxkart.com` with the Algo-ID in a header.

    Attributes:
        ALGO_IDENTIFIER (str): The Algo-ID of the approved non-registered strategy, sent as `X-Algo-Id` and in the body.
        ORDER_TYPE_CODES (dict): The shared order types to Stoxkart's.
        PRODUCT_CODES (dict): The shared products to Stoxkart's.
    """

    BROKER_NAME = 'stoxkart'
    IDENTIFIER_FIELD = 'broker_token'
    PLACE_SETTINGS_FIELDS = [
        'ucc_code',
        'api_key',
    ]
    CANCEL_SETTINGS_FIELDS = [
        'ucc_code',
        'api_key',
    ]
    MODIFY_SETTINGS_FIELDS = [
        'ucc_code',
        'api_key',
    ]
    MODIFIABLE_FIELDS = [
        'quantity',
        'disclosed_quantity',
        'price',
        'trigger_price',
        'order_type',
        'validity',
    ]
    MAXIMUM_IDLE_SECONDS = 300.0
    WARM_URL = 'https://openapi.stoxkart.com/'
    WARM_INTERVAL_SECONDS = 60.0
    MARKETS = {
        ('nse', 'securities', 'cash'): 'NSE',
        ('bse', 'securities', 'cash'): 'BSE',
        ('nse', 'securities', 'derivative'): 'NFO',
        ('bse', 'securities', 'derivative'): 'BFO',
        ('mcx', 'commodity', 'derivative'): 'MCX',
        ('nse', 'currency', 'derivative'): 'NSECD',
        ('bse', 'currency', 'derivative'): 'BSECD',
        ('ncdex', 'commodity', 'derivative'): 'NCDEX',
    }
    QUANTITY_UNITS = {
        ('mcx', 'commodity', 'derivative'): 'broker_lot_size',
        ('nse', 'currency', 'derivative'): 'broker_lot_size',
        ('bse', 'currency', 'derivative'): 'broker_lot_size',
        ('ncdex', 'commodity', 'derivative'): 'broker_lot_size',
    }
    ALGO_IDENTIFIER = '99999'
    ORDER_TYPE_CODES = {
        'MARKET': 'MARKET',
        'LIMIT': 'LIMIT',
        'SL': 'STOPLOSS_LIMIT',
        'SL-M': 'STOPLOSS_MARKET',
    }
    PRODUCT_CODES = {
        'CNC': 'DELIVERY',
        'MIS': 'INTRADAY',
        'NRML': 'CARRYFORWARD',
    }

    def headers(self, login, settings):
        """Builds Stoxkart's session headers.

        Args:
            login (dict): Stoxkart's decoded login.
            settings (dict): Stoxkart's decoded settings.

        Returns:
            dict: The headers.
        """
        return {
            'X-Client-Id': str(settings['ucc_code']),
            'X-Platform': 'api',
            'X-Api-Key': str(settings['api_key']),
            'X-Access-Token': str(login.get('access_token')),
            'X-Algo-Id': self.ALGO_IDENTIFIER,
        }

    def build_place_request(self, order, instrument, handle, login, settings):
        """Builds `POST /orders/{variety}`, where the variety is `amo` for an after-market order and `normal` otherwise.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            handle (dict): Stoxkart's order handle for the instrument.
            login (dict): Stoxkart's decoded login.
            settings (dict): Stoxkart's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        variety = 'normal'
        if order.after_market:
            variety = 'amo'
        json_body = {
            'exchange': self.MARKETS[instrument.market()],
            'token': str(handle.get('broker_token')),
            'action': order.transaction_type,
            'order_type': self.ORDER_TYPE_CODES[order.order_type],
            'product_type': self.PRODUCT_CODES[order.product],
            'quantity': str(order.quantity),
            'disclose_quantity': str(order.disclosed_quantity),
            'price': order.price_text,
            'trigger_price': order.trigger_price_text,
            'stop_loss_price': order.trigger_price_text,
            'trailing_stop_loss': '0',
            'validity': order.validity,
            'algo_id': self.ALGO_IDENTIFIER,
        }
        if order.tag:
            json_body['tag'] = order.tag
        return BrokerRequest(
            'POST',
            f'https://openapi.stoxkart.com/orders/{variety}',
            self.headers(login, settings),
            json_body=json_body,
            tag=order.tag,
        )

    def order_variety(self, stored_order):
        """The variety Stoxkart's cancel and modify paths name: the one the order scripts stored beside the order, then the order's own, then `normal`.

        Args:
            stored_order (StoredOrder): The order as Redis holds it.

        Returns:
            str: The variety, lower-cased.
        """
        variety = (
            stored_order.entry.get('variety')
            or stored_order.data.get('variety')
            or 'normal'
        )
        return str(variety).lower()

    def build_cancel_request(self, order_id, stored_order, login, settings):
        """Builds `DELETE /orders/{variety}/{order_id}`, with the variety the order scripts stored beside the order, then the order's own, then `normal`.

        Args:
            order_id (str): Stoxkart's order id.
            stored_order (StoredOrder): The order as Redis holds it.
            login (dict): Stoxkart's decoded login.
            settings (dict): Stoxkart's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        variety = self.order_variety(stored_order)
        return BrokerRequest(
            'DELETE',
            f'https://openapi.stoxkart.com/orders/{variety}/{order_id}',
            self.headers(login, settings),
        )

    def build_modify_request(
        self,
        order_id,
        stored_order,
        modification,
        login,
        settings,
    ):
        """Builds `PUT /orders/{variety}/{order_id}` with the body Stoxkart documents for a modification, which restates the exchange and token but not the side or product.

        Args:
            order_id (str): Stoxkart's order id.
            stored_order (StoredOrder): The order as Redis holds it.
            modification (OrderModification): The order after the change.
            login (dict): Stoxkart's decoded login.
            settings (dict): Stoxkart's decoded settings.

        Returns:
            BrokerRequest: The request.

        Raises:
            OrderNotReadyError: When Redis does not hold the order's exchange, token or validity.
        """
        missing = (
            modification.exchange is None
            or modification.instrument_token is None
        )
        if missing:
            message = (
                "Redis does not hold this Stoxkart order's exchange and token yet, so try again after Stoxkart's next order book poll"
            )
            raise OrderNotReadyError(message)
        variety = self.order_variety(stored_order)
        json_body = {
            'exchange': modification.exchange,
            'token': modification.instrument_token,
            'order_type': self.ORDER_TYPE_CODES[modification.order_type],
            'quantity': str(modification.quantity),
            'disclose_quantity': str(modification.disclosed_quantity),
            'price': modification.price_text,
            'trigger_price': modification.trigger_price_text,
            'stop_loss_price': modification.trigger_price_text,
            'validity': self.stored_value(modification.validity, 'validity'),
        }
        return BrokerRequest(
            'PUT',
            f'https://openapi.stoxkart.com/orders/{variety}/{order_id}',
            self.headers(login, settings),
            json_body=json_body,
        )

    def read_order_id(self, response_fields):
        """Reads `data.order_id`, or `order_id` when the body has no `data`.

        Args:
            response_fields (dict): Stoxkart's JSON body.

        Returns:
            object: The order id, or None.
        """
        data = response_fields.get('data', response_fields)
        if isinstance(data, dict):
            return data.get('order_id')
        return None
