"""How Zerodha's Kite Connect takes and cancels orders."""

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)


class ZerodhaOrders(BrokerOrders):
    """Zerodha's order requests, sent as forms to `api.kite.trade`.

    Attributes:
        SETTLED_REFUSALS (list): The Kite exception names that settle a server error as a refusal.
    """

    BROKER_NAME = 'zerodha'
    IDENTIFIER_FIELD = 'order_symbol'
    PLACE_SETTINGS_FIELDS = [
        'api_key',
    ]
    CANCEL_SETTINGS_FIELDS = [
        'api_key',
    ]
    MAXIMUM_IDLE_SECONDS = 300.0
    WARM_URL = 'https://api.kite.trade/'
    WARM_INTERVAL_SECONDS = 60.0
    MARKETS = {
        ('nse', 'securities', 'cash'): 'NSE',
        ('bse', 'securities', 'cash'): 'BSE',
        ('nse', 'securities', 'derivative'): 'NFO',
        ('bse', 'securities', 'derivative'): 'BFO',
    }
    SETTLED_REFUSALS = [
        'InputException',
        'OrderException',
        'MarginException',
        'HoldingException',
        'PermissionException',
        'TokenException',
    ]

    def headers(self, login, settings):
        """Builds Kite's session headers.

        Args:
            login (dict): Zerodha's decoded login.
            settings (dict): Zerodha's decoded settings.

        Returns:
            dict: The headers.
        """
        login_token = str(login.get('access_token'))
        return {
            'X-Kite-Version': '3',
            'Authorization': f'token {settings["api_key"]}:{login_token}',
        }

    def build_place_request(self, order, instrument, handle, login, settings):
        """Builds `POST /orders/{variety}`, where the variety is `amo` for an after-market order and `regular` otherwise.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            handle (dict): Zerodha's order handle for the instrument.
            login (dict): Zerodha's decoded login.
            settings (dict): Zerodha's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        variety = 'regular'
        if order.after_market:
            variety = 'amo'
        form = {
            'tradingsymbol': handle.get('order_symbol'),
            'exchange': self.MARKETS[instrument.market()],
            'transaction_type': order.transaction_type,
            'order_type': order.order_type,
            'quantity': order.quantity,
            'product': order.product,
            'validity': order.validity,
            'price': order.price_text,
            'trigger_price': order.trigger_price_text,
            'disclosed_quantity': order.disclosed_quantity,
        }
        if order.tag:
            form['tag'] = order.tag
        return BrokerRequest(
            'POST',
            f'https://api.kite.trade/orders/{variety}',
            self.headers(login, settings),
            data=form,
            shown_form=form,
            tag=order.tag,
        )

    def build_cancel_request(self, order_id, stored_order, login, settings):
        """Builds `DELETE /orders/{variety}/{order_id}`, with the variety Kite stored on the order.

        Args:
            order_id (str): Zerodha's order id.
            stored_order (StoredOrder): The order as Redis holds it.
            login (dict): Zerodha's decoded login.
            settings (dict): Zerodha's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        variety = str(stored_order.data.get('variety') or 'regular')
        return BrokerRequest(
            'DELETE',
            f'https://api.kite.trade/orders/{variety}/{order_id}',
            self.headers(login, settings),
        )

    def read_order_id(self, response_fields):
        """Reads `data.order_id`.

        Args:
            response_fields (dict): Kite's JSON body.

        Returns:
            object: The order id, or None.
        """
        data = response_fields.get('data')
        if isinstance(data, dict):
            return data.get('order_id')
        return None

    def is_settled_refusal(self, error_code):
        """Whether the error names one of Kite's refusal exceptions.

        Args:
            error_code (str): The error code, which is Kite's `error_type`.

        Returns:
            bool: True for a settled refusal.
        """
        return error_code in self.SETTLED_REFUSALS
