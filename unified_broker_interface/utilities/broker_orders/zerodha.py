"""How Zerodha's Kite Connect takes, modifies and cancels orders."""

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)


class ZerodhaOrders(BrokerOrders):
    """Zerodha's order requests, sent as forms to `api.kite.trade`.

    Attributes:
        SETTLED_REFUSALS (list): The Kite exception names that settle a server error as a refusal.
        MARKET_PROTECTED_ORDER_TYPES (list): The order types a modification changing to them sends `market_protection` with.
    """

    BROKER_NAME = 'zerodha'
    IDENTIFIER_FIELD = 'order_symbol'
    PLACE_SETTINGS_FIELDS = [
        'api_key',
    ]
    CANCEL_SETTINGS_FIELDS = [
        'api_key',
    ]
    MODIFY_SETTINGS_FIELDS = [
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
    MARKET_PROTECTED_ORDER_TYPES = [
        'MARKET',
        'SL-M',
    ]
    MAXIMUM_IDLE_SECONDS = 300.0
    WARM_URL = 'https://api.kite.trade/'
    WARM_INTERVAL_SECONDS = 60.0
    MARKETS = {
        ('nse', 'securities', 'cash'): 'NSE',
        ('bse', 'securities', 'cash'): 'BSE',
        ('nse', 'securities', 'derivative'): 'NFO',
        ('bse', 'securities', 'derivative'): 'BFO',
        ('mcx', 'commodity', 'derivative'): 'MCX',
        ('nse', 'commodity', 'derivative'): 'NCO',
        ('nse', 'currency', 'derivative'): 'CDS',
        ('bse', 'currency', 'derivative'): 'BCD',
    }
    QUANTITY_UNITS = {
        ('mcx', 'commodity', 'derivative'): 'broker_lot_size',
        ('nse', 'commodity', 'derivative'): 'broker_lot_size',
        ('nse', 'currency', 'derivative'): 'broker_lot_size',
        ('bse', 'currency', 'derivative'): 'broker_lot_size',
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

    def build_modify_request(
        self,
        order_id,
        stored_order,
        modification,
        login,
        settings,
    ):
        """Builds `PUT /orders/{variety}/{order_id}`, with the variety Kite stored on the order.

        Kite changes only the fields a modification sends. The order type is always sent, and a price or trigger price whenever the order type after the change takes one, because a stop-loss order sent only a new quantity has been answered with success and left unchanged. A quantity, disclosed quantity or validity is sent only when the caller changed it, because Kite reads an omitted quantity as leaving the pending quantity alone. A change to MARKET or SL-M sends `market_protection` of -1, Kite's automatic protection, which Kite has required on such placements since April 2026.

        Args:
            order_id (str): Zerodha's order id.
            stored_order (StoredOrder): The order as Redis holds it.
            modification (OrderModification): The order after the change.
            login (dict): Zerodha's decoded login.
            settings (dict): Zerodha's decoded settings.

        Returns:
            BrokerRequest: The request.
        """
        variety = str(stored_order.data.get('variety') or 'regular')
        form = {
            'order_type': modification.order_type,
        }
        if modification.changes('quantity'):
            form['quantity'] = modification.quantity
        if modification.price is not None:
            form['price'] = modification.price_text
        if modification.trigger_price is not None:
            form['trigger_price'] = modification.trigger_price_text
        if modification.changes('disclosed_quantity'):
            form['disclosed_quantity'] = modification.disclosed_quantity
        if modification.changes('validity'):
            form['validity'] = modification.validity
        protected = (
            modification.order_type in self.MARKET_PROTECTED_ORDER_TYPES
        )
        if modification.changes('order_type') and protected:
            form['market_protection'] = '-1'
        return BrokerRequest(
            'PUT',
            f'https://api.kite.trade/orders/{variety}/{order_id}',
            self.headers(login, settings),
            data=form,
            shown_form=form,
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
