"""Writes a small broker order class on top of `BrokerOrders` and asks it, step by step, whether it can take an order.

A broker order class sets a few class attributes and implements the request builders; `BrokerOrders` supplies everything else. Before anything is built, `place_skip_reason` decides whether the broker can take the order at all: whether it lists the instrument's market in `MARKETS`, knows how it counts quantity there, has a handle for the instrument, has a login and the settings it needs, and takes that order type. Each failed check gives the reason a caller sees in `skipped`.

The subclass here is made up: a broker that takes NSE cash and MCX commodity futures, counts MCX quantity in lots, needs a `client_code` setting and takes no stop-loss orders. For a commodity, `order_quantities` converts the caller's units into the broker's lots using the morning's trusted contract size. The logins and settings are decoded from made-up text as Redis would hold it. Nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/base/BrokerOrders/example_1_can_this_broker_take_the_order.py
"""

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)


class ExampleBrokerOrders(BrokerOrders):
    """A made-up broker that takes NSE cash and MCX commodity futures orders as JSON."""

    BROKER_NAME = 'example_broker'
    IDENTIFIER_FIELD = 'broker_token'
    PLACE_SETTINGS_FIELDS = [
        'client_code',
    ]
    MARKETS = {
        (
            'nse',
            'securities',
            'cash',
        ): 'NSE_CASH',
        (
            'mcx',
            'commodity',
            'derivative',
        ): 'MCX_FO',
    }
    QUANTITY_UNITS = {
        (
            'mcx',
            'commodity',
            'derivative',
        ): 'lots',
    }
    TAKES_TRIGGERED_ORDERS = False

    def build_place_request(self, order, instrument, handle, login, settings):
        """Builds the made-up broker's place request.

        Args:
            order (PlaceOrderRequest): The validated order, with quantities in the broker's terms.
            instrument (Instrument): The tradeable instrument.
            handle (dict): The broker's order handle.
            login (dict): The decoded login.
            settings (dict): The decoded settings.

        Returns:
            BrokerRequest: The request, not yet sent.
        """
        return BrokerRequest(
            'POST',
            'https://api.example-broker.in/orders',
            {
                'Authorization': login['access_token'],
            },
            json_body={
                'client': settings['client_code'],
                'segment': self.MARKETS[instrument.market()],
                'token': handle['broker_token'],
                'side': order.transaction_type,
                'quantity': order.quantity,
            },
        )


class CanThisBrokerTakeTheOrderExample:
    """Runs the made-up broker's checks against several orders.

    Attributes:
        broker_orders (ExampleBrokerOrders): The broker's order class.
        login (object): The decoded login.
        settings (dict): The decoded settings.
        equity (Instrument): RELIANCE on the NSE.
        crude (Instrument): A crude oil future on the MCX, with a trusted size of 100 barrels a lot.
    """

    def __init__(self):
        """Builds the order class, decodes the login and settings, and builds two instruments.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = ExampleBrokerOrders()
        self.login = self.broker_orders.decode_login('{"access_token": "example-token"}')
        self.settings = self.broker_orders.decode_settings('{"client_code": "C1001"}')
        self.equity = Instrument(
            '11111111-1111-5111-8111-000000000001',
            {
                'segment': 'nse_equities',
            },
            {
                'example_broker': {
                    'broker_token': '2885',
                    'lot_size': 1.0,
                    'tick_size': 0.1,
                },
            },
        )
        self.crude = Instrument(
            '22222222-2222-5222-8222-000000000001',
            {
                'segment': 'mcx_commodity_futures',
            },
            {
                'example_broker': {
                    'broker_token': '569900',
                    'lot_size': 100.0,
                    'tick_size': 1.0,
                },
            },
            {
                'units_per_lot': '100',
                'status': 'confirmed',
                'tradeable': True,
            },
        )

    def order(self, order_type, quantity, **fields):
        """Validates an order body.

        Args:
            order_type (str): The order type.
            quantity (int): The quantity in units.
            **fields (object): Other body fields, such as prices.

        Returns:
            PlaceOrderRequest: The validated order.
        """
        body = {
            'instrument_id': '11111111-1111-5111-8111-000000000001',
            'transaction_type': 'BUY',
            'product': 'NRML',
            'order_type': order_type,
            'quantity': quantity,
        }
        body.update(fields)
        return PlaceOrderRequest(body)

    def skip_reason(self, label, order, instrument, login, settings):
        """Prints why the broker would be passed over, or that it can take the order.

        Args:
            label (str): What the case is.
            order (PlaceOrderRequest): The order.
            instrument (Instrument): The instrument.
            login (object): The decoded login.
            settings (dict): The decoded settings.

        Returns:
            None: This method returns nothing.
        """
        handle = instrument.handles.get('example_broker')
        reason = self.broker_orders.place_skip_reason(order, instrument, handle, login, settings)
        if reason is None:
            reason = 'can take it'
        print(f'{label}: {reason}')

    def run(self):
        """Prints the result of each check.

        Returns:
            None: This method returns nothing.
        """
        market_order = self.order('MARKET', 10)
        stop_order = self.order('SL-M', 10, trigger_price='2480')
        currency = Instrument(
            '33333333-3333-5333-8333-000000000001',
            {
                'segment': 'nse_currency_futures',
            },
            {},
        )
        self.skip_reason('Market order for RELIANCE', market_order, self.equity, self.login, self.settings)
        self.skip_reason('Stop-loss order', stop_order, self.equity, self.login, self.settings)
        self.skip_reason('Currency future', market_order, currency, self.login, self.settings)
        self.skip_reason('No login in Redis', market_order, self.equity, self.broker_orders.decode_login(None), self.settings)
        self.skip_reason('Login is not JSON', market_order, self.equity, self.broker_orders.decode_login('expired'), self.settings)
        self.skip_reason('Settings are a list', market_order, self.equity, self.login, self.broker_orders.decode_settings('[]'))
        needed_settings = [
            'client_code',
            'api_secret',
        ]
        print(f'Missing settings when client_code and api_secret are needed: {self.broker_orders.missing_settings(self.settings, needed_settings)}')
        crude_handle = self.crude.handles['example_broker']
        crude_order = self.order('MARKET', 300, disclosed_quantity=100)
        self.skip_reason('Crude oil future', crude_order, self.crude, self.login, self.settings)
        print(f'Crude quantities in the broker terms: {self.broker_orders.order_quantities(crude_order, self.crude, crude_handle)}')
        print(f'One quantity of 500 barrels: {self.broker_orders.broker_quantity(500, self.crude, crude_handle)} lots')
        print(f'Equity quantity is unchanged: {self.broker_orders.broker_quantity(10, self.equity, self.equity.handles["example_broker"])}')
        print(f'Broker lot size from the crude handle: {self.broker_orders.broker_lot_size(crude_handle)}')
        fractional_handle = {
            'lot_size': 0.5,
        }
        print(f'Broker lot size of 0.5: {self.broker_orders.broker_lot_size(fractional_handle)}')
        print(f'Quantity conversion problem for crude: {self.broker_orders.quantity_conversion_problem(self.crude, crude_handle)}')
        print(f'Handle check beyond the identifier: {self.broker_orders.handle_skip_reason(crude_handle)}')
        print(f'Login check beyond the access token: {self.broker_orders.login_skip_reason(self.login)}')
        print(f'Takes only securities: {self.broker_orders.takes_only_securities()}')
        print(f'Stored exchange NSE_CASH matches RELIANCE: {self.broker_orders.stored_exchange_matches(self.equity, "nse_cash")}')
        print(f'Stored exchange BSE_CASH matches RELIANCE: {self.broker_orders.stored_exchange_matches(self.equity, "BSE_CASH")}')
        request = self.broker_orders.build_place_request(market_order, self.equity, self.equity.handles['example_broker'], self.login, self.settings)
        print(f'Request built: {request.shown()}')


if __name__ == '__main__':
    CanThisBrokerTakeTheOrderExample().run()
