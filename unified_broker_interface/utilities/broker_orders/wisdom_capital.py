"""How Wisdom Capital's XTS interactive API takes, modifies and cancels orders."""

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)


class WisdomCapitalOrders(BrokerOrders):
    """Wisdom Capital's order requests, sent as JSON to `trade.wisdomcapital.in` without checking its certificate, which does not match its host.

    Attributes:
        ORDER_TYPE_CODES (dict): The shared order types to XTS's.
        SETTLED_REFUSAL_PREFIXES (tuple): The lower-case error code prefixes that settle a server error as a refusal.
    """

    BROKER_NAME = 'wisdom_capital'
    IDENTIFIER_FIELD = 'broker_token'
    PLACE_SETTINGS_FIELDS = [
        'ucc_code',
    ]
    CANCEL_SETTINGS_FIELDS = [
        'ucc_code',
    ]
    MODIFY_SETTINGS_FIELDS = [
        'ucc_code',
    ]
    MODIFIABLE_FIELDS = [
        'quantity',
        'disclosed_quantity',
        'price',
        'trigger_price',
        'order_type',
        'validity',
    ]
    MAXIMUM_IDLE_SECONDS = 45.0
    WARM_URL = 'https://trade.wisdomcapital.in/'
    WARM_INTERVAL_SECONDS = 15.0
    MARKETS = {
        ('nse', 'securities', 'cash'): 'NSECM',
        ('bse', 'securities', 'cash'): 'BSECM',
        ('nse', 'securities', 'derivative'): 'NSEFO',
        ('bse', 'securities', 'derivative'): 'BSEFO',
        ('mcx', 'commodity', 'derivative'): 'MCXFO',
        ('nse', 'commodity', 'derivative'): 'NSECO',
        ('nse', 'currency', 'derivative'): 'NSECD',
        ('bse', 'currency', 'derivative'): 'BSECD',
        ('ncdex', 'commodity', 'derivative'): 'NCDEX',
    }
    QUANTITY_UNITS = {
        ('mcx', 'commodity', 'derivative'): 'broker_lot_size',
        ('nse', 'commodity', 'derivative'): 'broker_lot_size',
        ('nse', 'currency', 'derivative'): 'broker_lot_size',
        ('bse', 'currency', 'derivative'): 'broker_lot_size',
        ('ncdex', 'commodity', 'derivative'): 'broker_lot_size',
    }
    TAKES_AFTER_MARKET = False
    VERIFY_CERTIFICATE = False
    ORDER_TYPE_CODES = {
        'MARKET': 'MARKET',
        'LIMIT': 'LIMIT',
        'SL': 'STOPLIMIT',
        'SL-M': 'STOPMARKET',
    }
    SETTLED_REFUSAL_PREFIXES = (
        'e-orders',
        'e-order',
        'e-rms',
    )

    def handle_skip_reason(self, handle):
        """Passes Wisdom Capital over when its instrument id is not numeric, because XTS takes it as an integer.

        Args:
            handle (dict): Wisdom Capital's order handle.

        Returns:
            str | None: The reason, or None.
        """
        if not str(handle.get('broker_token')).isdigit():
            return 'its mapping carries no numeric instrument id'
        return None

    def headers(self, login):
        """Builds XTS's session headers.

        Args:
            login (dict): Wisdom Capital's decoded login.

        Returns:
            dict: The headers.
        """
        return {
            'authorization': str(login.get('access_token')),
        }

    def build_place_request(self, order, instrument, handle, login, settings):
        """Builds `POST /interactive/orders`.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            handle (dict): Wisdom Capital's order handle for the instrument.
            login (dict): Wisdom Capital's decoded login.
            settings (dict): Wisdom Capital's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        json_body = {
            'exchangeSegment': self.MARKETS[instrument.market()],
            'exchangeInstrumentID': int(str(handle.get('broker_token'))),
            'productType': order.product,
            'orderType': self.ORDER_TYPE_CODES[order.order_type],
            'orderSide': order.transaction_type,
            'timeInForce': order.validity,
            'disclosedQuantity': order.disclosed_quantity,
            'orderQuantity': order.quantity,
            'limitPrice': order.price_number,
            'stopPrice': order.trigger_price_number,
            'orderUniqueIdentifier': order.tag or 'ubi',
            'clientID': str(settings['ucc_code']),
        }
        return BrokerRequest(
            'POST',
            'https://trade.wisdomcapital.in/interactive/orders',
            self.headers(login),
            json_body=json_body,
            verify_certificate=self.VERIFY_CERTIFICATE,
            tag=order.tag,
        )

    def application_order_id(self, order_id):
        """The order id as XTS takes it: an integer when it is all digits, and the text otherwise.

        Args:
            order_id (str): Wisdom Capital's application order id.

        Returns:
            int | str: The order id.
        """
        if order_id.isdigit():
            return int(order_id)
        return order_id

    def unique_identifier(self, stored_order):
        """The `OrderUniqueIdentifier` stored on the order, or `ubi`, the value `place` sends when there is no tag.

        Args:
            stored_order (StoredOrder): The order as Redis holds it.

        Returns:
            str: The identifier.
        """
        unique_identifier = stored_order.data.get('OrderUniqueIdentifier')
        if not unique_identifier:
            unique_identifier = 'ubi'
        return str(unique_identifier)

    def build_cancel_request(self, order_id, stored_order, login, settings):
        """Builds `DELETE /interactive/orders` with the order's ids in the query string.

        Args:
            order_id (str): Wisdom Capital's application order id.
            stored_order (StoredOrder): The order as Redis holds it.
            login (dict): Wisdom Capital's decoded login.
            settings (dict): Wisdom Capital's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        return BrokerRequest(
            'DELETE',
            'https://trade.wisdomcapital.in/interactive/orders',
            self.headers(login),
            params={
                'appOrderID': self.application_order_id(order_id),
                'orderUniqueIdentifier': self.unique_identifier(stored_order),
                'clientID': str(settings['ucc_code']),
            },
            verify_certificate=self.VERIFY_CERTIFICATE,
        )

    def build_modify_request(
        self,
        order_id,
        stored_order,
        modification,
        login,
        settings,
    ):
        """Builds `PUT /interactive/orders` with every field XTS requires restated for the order after the change.

        Args:
            order_id (str): Wisdom Capital's application order id.
            stored_order (StoredOrder): The order as Redis holds it.
            modification (OrderModification): The order after the change.
            login (dict): Wisdom Capital's decoded login.
            settings (dict): Wisdom Capital's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        json_body = {
            'appOrderID': self.application_order_id(order_id),
            'modifiedProductType': modification.product,
            'modifiedOrderType': self.ORDER_TYPE_CODES[modification.order_type],
            'modifiedOrderQuantity': modification.quantity,
            'modifiedDisclosedQuantity': modification.disclosed_quantity,
            'modifiedLimitPrice': modification.price_number,
            'modifiedStopPrice': modification.trigger_price_number,
            'modifiedTimeInForce': modification.validity,
            'orderUniqueIdentifier': self.unique_identifier(stored_order),
            'clientID': str(settings['ucc_code']),
        }
        return BrokerRequest(
            'PUT',
            'https://trade.wisdomcapital.in/interactive/orders',
            self.headers(login),
            json_body=json_body,
            verify_certificate=self.VERIFY_CERTIFICATE,
        )

    def read_order_id(self, response_fields):
        """Reads `result.AppOrderID`.

        Args:
            response_fields (dict): XTS's JSON body.

        Returns:
            object: The order id, or None.
        """
        result = response_fields.get('result')
        if isinstance(result, dict):
            return result.get('AppOrderID')
        return None

    def read_refusal(self, response_fields):
        """Reads a refusal from a `type` other than `success`.

        Args:
            response_fields (dict): XTS's JSON body.

        Returns:
            object: The refusal message, or None.
        """
        xts_type = response_fields.get('type')
        if xts_type is None or xts_type == 'success':
            return None
        refusal = response_fields.get('description')
        if not refusal:
            refusal = response_fields.get('message')
        if not refusal:
            refusal = f'type {xts_type}'
        return refusal

    def is_settled_refusal(self, error_code):
        """Whether the lower-cased error code starts with one of XTS's refusal prefixes.

        Args:
            error_code (str): The error code.

        Returns:
            bool: True for a settled refusal.
        """
        return error_code.lower().startswith(self.SETTLED_REFUSAL_PREFIXES)
