"""How INDmoney's INDstocks API takes and cancels orders."""

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)


class IndmoneyOrders(BrokerOrders):
    """INDmoney's order requests, sent as JSON to `api.indstocks.com`.

    Attributes:
        PRODUCT_CODES (dict): The shared products to INDmoney's.
        ALGO_IDENTIFIERS (dict): Each exchange to the Algo-ID INDmoney's order request carries.
        SETTLED_REFUSAL_MARKERS (list): Texts that settle a server error as a refusal when the lower-cased error code contains one.
    """

    BROKER_NAME = 'indmoney'
    IDENTIFIER_FIELD = 'broker_token'
    PLACE_SETTINGS_FIELDS = []
    CANCEL_SETTINGS_FIELDS = []
    MARKETS = {
        ('nse', 'securities', 'cash'): 'EQUITY',
        ('bse', 'securities', 'cash'): 'EQUITY',
        ('nse', 'securities', 'derivative'): 'DERIVATIVE',
        ('bse', 'securities', 'derivative'): 'DERIVATIVE',
    }
    TAKES_TRIGGERED_ORDERS = False
    PRODUCT_CODES = {
        'CNC': 'CNC',
        'MIS': 'INTRADAY',
        'NRML': 'MARGIN',
    }
    ALGO_IDENTIFIERS = {
        'nse': '99999',
        'bse': '9999999999999999',
    }
    SETTLED_REFUSAL_MARKERS = [
        'validation',
        'order',
        'insufficient',
        'invalid',
        'margin',
    ]

    def headers(self, login):
        """Builds INDmoney's session headers.

        Args:
            login (dict): INDmoney's decoded login.

        Returns:
            dict: The headers.
        """
        return {
            'Authorization': str(login.get('access_token')),
        }

    def build_place_request(self, order, instrument, handle, login, settings):
        """Builds `POST /order`.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            handle (dict): INDmoney's order handle for the instrument.
            login (dict): INDmoney's decoded login.
            settings (dict): INDmoney's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        json_body = {
            'txn_type': order.transaction_type,
            'exchange': instrument.exchange.upper(),
            'segment': self.MARKETS[instrument.market()],
            'product': self.PRODUCT_CODES[order.product],
            'order_type': order.order_type,
            'validity': order.validity,
            'security_id': str(handle.get('broker_token')),
            'qty': order.quantity,
            'algo_id': self.ALGO_IDENTIFIERS[instrument.exchange],
            'limit_price': order.price_number,
            'is_amo': order.after_market,
        }
        if order.tag:
            json_body['remarks'] = order.tag
        return BrokerRequest(
            'POST',
            'https://api.indstocks.com/order',
            self.headers(login),
            json_body=json_body,
            tag=order.tag,
        )

    def build_cancel_request(self, order_id, stored_order, login, settings):
        """Builds `POST /order/cancel`, with the stored segment or, when there is none, one guessed from the order id.

        Args:
            order_id (str): INDmoney's order id.
            stored_order (StoredOrder): The order as Redis holds it.
            login (dict): INDmoney's decoded login.
            settings (dict): INDmoney's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        segment = stored_order.data.get('segment')
        if not segment:
            if order_id.upper().startswith('DRV'):
                segment = 'DERIVATIVE'
            else:
                segment = 'EQUITY'
        return BrokerRequest(
            'POST',
            'https://api.indstocks.com/order/cancel',
            self.headers(login),
            json_body={
                'order_id': order_id,
                'segment': str(segment),
            },
        )

    def read_order_id(self, response_fields):
        """Reads `data.order_id`.

        Args:
            response_fields (dict): INDmoney's JSON body.

        Returns:
            object: The order id, or None.
        """
        data = response_fields.get('data')
        if isinstance(data, dict):
            return data.get('order_id')
        return None

    def read_refusal(self, response_fields):
        """Reads a refusal from a `status` other than `success`; a body without `status` counts as success.

        Args:
            response_fields (dict): INDmoney's JSON body.

        Returns:
            object: The refusal message, or None.
        """
        status_text = str(response_fields.get('status', 'success'))
        if status_text.lower() == 'success':
            return None
        refusal = response_fields.get('message')
        if not refusal:
            refusal = f'status {status_text}'
        return refusal

    def is_settled_refusal(self, error_code):
        """Whether the lower-cased error code contains one of INDmoney's refusal markers.

        Args:
            error_code (str): The error code.

        Returns:
            bool: True for a settled refusal.
        """
        lowered_code = error_code.lower()
        for marker in self.SETTLED_REFUSAL_MARKERS:
            if marker in lowered_code:
                return True
        return False
