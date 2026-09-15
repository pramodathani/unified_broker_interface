"""How Dhan's v2 API takes and cancels orders."""

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)


class DhanOrders(BrokerOrders):
    """Dhan's order requests, sent as JSON to `api.dhan.co`.

    Attributes:
        ORDER_TYPE_CODES (dict): The shared order types to Dhan's.
        PRODUCT_CODES (dict): The shared products to Dhan's.
        SETTLED_REFUSAL_MARKERS (list): Texts that settle a server error as a refusal when the lower-cased error code contains one.
    """

    BROKER_NAME = 'dhan'
    IDENTIFIER_FIELD = 'broker_token'
    PLACE_SETTINGS_FIELDS = [
        'client_id',
    ]
    CANCEL_SETTINGS_FIELDS = []
    MAXIMUM_IDLE_SECONDS = 180.0
    WARM_URL = 'https://api.dhan.co/'
    WARM_INTERVAL_SECONDS = 60.0
    MARKETS = {
        ('nse', 'securities', 'cash'): 'NSE_EQ',
        ('bse', 'securities', 'cash'): 'BSE_EQ',
        ('nse', 'securities', 'derivative'): 'NSE_FNO',
        ('bse', 'securities', 'derivative'): 'BSE_FNO',
        ('mcx', 'commodity', 'derivative'): 'MCX_COMM',
    }
    QUANTITY_UNITS = {
        ('mcx', 'commodity', 'derivative'): 'broker_lot_size',
    }
    ORDER_TYPE_CODES = {
        'MARKET': 'MARKET',
        'LIMIT': 'LIMIT',
        'SL': 'STOP_LOSS',
        'SL-M': 'STOP_LOSS_MARKET',
    }
    PRODUCT_CODES = {
        'CNC': 'CNC',
        'MIS': 'INTRADAY',
        'NRML': 'MARGIN',
    }
    SETTLED_REFUSAL_MARKERS = [
        'input',
        'order',
        'rate_limit',
        'rate limit',
        'access',
    ]

    def headers(self, login):
        """Builds Dhan's session headers.

        Args:
            login (dict): Dhan's decoded login.

        Returns:
            dict: The headers.
        """
        return {
            'access-token': str(login.get('access_token')),
        }

    def build_place_request(self, order, instrument, handle, login, settings):
        """Builds `POST /v2/orders`.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            handle (dict): Dhan's order handle for the instrument.
            login (dict): Dhan's decoded login.
            settings (dict): Dhan's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        json_body = {
            'dhanClientId': str(settings['client_id']),
            'transactionType': order.transaction_type,
            'exchangeSegment': self.MARKETS[instrument.market()],
            'productType': self.PRODUCT_CODES[order.product],
            'orderType': self.ORDER_TYPE_CODES[order.order_type],
            'validity': order.validity,
            'securityId': str(handle.get('broker_token')),
            'quantity': order.quantity,
            'disclosedQuantity': order.disclosed_quantity,
            'price': order.price_number,
            'triggerPrice': order.trigger_price_number,
            'afterMarketOrder': order.after_market,
        }
        if order.after_market:
            json_body['amoTime'] = 'OPEN'
        if order.tag:
            json_body['correlationId'] = order.tag
        return BrokerRequest(
            'POST',
            'https://api.dhan.co/v2/orders',
            self.headers(login),
            json_body=json_body,
            tag=order.tag,
        )

    def build_cancel_request(self, order_id, stored_order, login, settings):
        """Builds `DELETE /v2/orders/{order_id}`.

        Args:
            order_id (str): Dhan's order id.
            stored_order (StoredOrder): The order as Redis holds it.
            login (dict): Dhan's decoded login.
            settings (dict): Dhan's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        return BrokerRequest(
            'DELETE',
            f'https://api.dhan.co/v2/orders/{order_id}',
            self.headers(login),
        )

    def read_order_id(self, response_fields):
        """Reads `orderId`.

        Args:
            response_fields (dict): Dhan's JSON body.

        Returns:
            object: The order id, or None.
        """
        return response_fields.get('orderId')

    def is_settled_refusal(self, error_code):
        """Whether the lower-cased error code contains one of Dhan's refusal markers.

        Args:
            error_code (str): The error code, which is Dhan's `errorType` or `errorCode`.

        Returns:
            bool: True for a settled refusal.
        """
        lowered_code = error_code.lower()
        for marker in self.SETTLED_REFUSAL_MARKERS:
            if marker in lowered_code:
                return True
        return False
