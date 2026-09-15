"""How Groww's trade API takes and cancels orders."""

import uuid

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    CancelNotReadyError,
)


class GrowwOrders(BrokerOrders):
    """Groww's order requests, sent as JSON to `api.groww.in`.

    Attributes:
        ORDER_TYPE_CODES (dict): The shared order types to Groww's.
        SETTLED_REFUSALS (list): The Groww error codes that settle a server error as a refusal.
    """

    BROKER_NAME = 'groww'
    IDENTIFIER_FIELD = 'order_symbol'
    PLACE_SETTINGS_FIELDS = []
    CANCEL_SETTINGS_FIELDS = []
    MAXIMUM_IDLE_SECONDS = 300.0
    WARM_URL = 'https://api.groww.in/'
    WARM_INTERVAL_SECONDS = 60.0
    MARKETS = {
        ('nse', 'securities', 'cash'): 'CASH',
        ('bse', 'securities', 'cash'): 'CASH',
        ('nse', 'securities', 'derivative'): 'FNO',
        ('bse', 'securities', 'derivative'): 'FNO',
        ('mcx', 'commodity', 'derivative'): 'COMMODITY',
        ('nse', 'commodity', 'derivative'): 'COMMODITY',
    }
    QUANTITY_UNITS = {
        ('mcx', 'commodity', 'derivative'): 'broker_lot_size',
        ('nse', 'commodity', 'derivative'): 'broker_lot_size',
    }
    TAKES_AFTER_MARKET = False
    ORDER_TYPE_CODES = {
        'MARKET': 'MARKET',
        'LIMIT': 'LIMIT',
        'SL': 'SL',
        'SL-M': 'SL_M',
    }
    SETTLED_REFUSALS = [
        'GA001',
        'GA004',
        'GA005',
        'GA006',
        'GA007',
    ]

    def headers(self, login):
        """Builds Groww's session headers.

        Args:
            login (dict): Groww's decoded login.

        Returns:
            dict: The headers.
        """
        return {
            'Accept': 'application/json',
            'Authorization': f'Bearer {login.get("access_token")}',
            'X-API-Version': '1.0',
        }

    def build_place_request(self, order, instrument, handle, login, settings):
        """Builds `POST /v1/order/create`, with a generated `order_reference_id` that is also answered as the order's tag.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            handle (dict): Groww's order handle for the instrument.
            login (dict): Groww's decoded login.
            settings (dict): Groww's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        reference_start = (order.tag or 'ubi')[:7]
        broker_tag = f'{reference_start}-{uuid.uuid4().hex[:12]}'
        json_body = {
            'trading_symbol': handle.get('order_symbol'),
            'quantity': order.quantity,
            'price': order.price_number,
            'trigger_price': order.trigger_price_number,
            'validity': order.validity,
            'exchange': instrument.exchange.upper(),
            'segment': self.MARKETS[instrument.market()],
            'product': order.product,
            'order_type': self.ORDER_TYPE_CODES[order.order_type],
            'transaction_type': order.transaction_type,
            'order_reference_id': broker_tag,
        }
        return BrokerRequest(
            'POST',
            'https://api.groww.in/v1/order/create',
            self.headers(login),
            json_body=json_body,
            tag=broker_tag,
        )

    def build_cancel_request(self, order_id, stored_order, login, settings):
        """Builds `POST /v1/order/cancel` with the segment Groww stored on the order.

        Args:
            order_id (str): Groww's order id.
            stored_order (StoredOrder): The order as Redis holds it.
            login (dict): Groww's decoded login.
            settings (dict): Groww's decoded settings.

        Returns:
            BrokerRequest: The request.

        Raises:
            CancelNotReadyError: When the stored order has no segment, as after a websocket update.
        """
        segment = stored_order.data.get('segment')
        if not segment:
            message = (
                "Redis does not hold this Groww order's segment yet, so try again after Groww's next order book poll"
            )
            raise CancelNotReadyError(message)
        return BrokerRequest(
            'POST',
            'https://api.groww.in/v1/order/cancel',
            self.headers(login),
            json_body={
                'groww_order_id': order_id,
                'segment': str(segment),
            },
        )

    def read_order_id(self, response_fields):
        """Reads `payload.groww_order_id`.

        Args:
            response_fields (dict): Groww's JSON body.

        Returns:
            object: The order id, or None.
        """
        payload = response_fields.get('payload')
        if isinstance(payload, dict):
            return payload.get('groww_order_id')
        return None

    def read_refusal(self, response_fields):
        """Reads a refusal from a `status` other than `SUCCESS`.

        Args:
            response_fields (dict): Groww's JSON body.

        Returns:
            object: The refusal message, or None.
        """
        groww_status = response_fields.get('status')
        if groww_status is None or groww_status == 'SUCCESS':
            return None
        refusal = None
        nested_error = response_fields.get('error')
        if isinstance(nested_error, dict):
            refusal = nested_error.get('message')
        if not refusal:
            refusal = response_fields.get('message')
        if not refusal:
            refusal = f'status {groww_status}'
        return refusal

    def is_settled_refusal(self, error_code):
        """Whether the upper-cased error code is one of Groww's refusal codes.

        Args:
            error_code (str): The error code.

        Returns:
            bool: True for a settled refusal.
        """
        return error_code.upper() in self.SETTLED_REFUSALS
