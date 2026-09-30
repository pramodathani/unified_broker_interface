"""Runs the checks `BrokerOrders` makes before a cancel or a modification is built, on a small made-up broker.

A cancel or modification needs the broker's login and the settings its requests name; `cancel_problem` and `modify_problem` give the HTTP 503 message when something is missing. A modification also has to change only fields the broker's modify request can carry: `takes_modifications` says whether the broker modifies orders at all, and `modify_field_problem` refuses a field or an order type it cannot send. When a builder needs a value Redis does not hold yet, `stored_value` raises `OrderNotReadyError` instead of guessing.

The made-up broker can change the quantity, price, trigger price and order type but not the validity, needs an `api_key` to cancel, and takes no stop-loss orders. Its builders put the stored order's segment in the URL. The logins, settings and stored order are made-up values; nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/base/BrokerOrders/example_2_cancel_and_modify_checks.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.base import BrokerOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.modify_order_request import (
    ModifyOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_modification import (
    OrderModification,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    OrderNotReadyError,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)


class ExampleBrokerOrders(BrokerOrders):
    """A made-up broker that cancels and modifies orders through a segment in the URL."""

    BROKER_NAME = 'example_broker'
    CANCEL_SETTINGS_FIELDS = [
        'api_key',
    ]
    MODIFY_SETTINGS_FIELDS = [
        'api_key',
    ]
    MODIFIABLE_FIELDS = [
        'quantity',
        'price',
        'trigger_price',
        'order_type',
    ]
    TAKES_TRIGGERED_ORDERS = False

    def build_cancel_request(self, order_id, stored_order, login, settings):
        """Builds the cancel request.

        Args:
            order_id (str): The broker's order id.
            stored_order (StoredOrder): The order as Redis holds it.
            login (dict): The decoded login.
            settings (dict): The decoded settings.

        Returns:
            BrokerRequest: The request, not yet sent.

        Raises:
            OrderNotReadyError: When Redis does not hold the order's segment.
        """
        segment = self.stored_value(stored_order.data.get('segment'), 'segment')
        return BrokerRequest(
            'DELETE',
            f'https://api.example-broker.in/orders/{segment}/{order_id}',
            {
                'X-Api-Key': settings['api_key'],
            },
        )

    def build_modify_request(self, order_id, stored_order, modification, login, settings):
        """Builds the modify request with the whole order after the change.

        Args:
            order_id (str): The broker's order id.
            stored_order (StoredOrder): The order as Redis holds it.
            modification (OrderModification): The order after the change.
            login (dict): The decoded login.
            settings (dict): The decoded settings.

        Returns:
            BrokerRequest: The request, not yet sent.

        Raises:
            OrderNotReadyError: When Redis does not hold the order's segment.
        """
        segment = self.stored_value(stored_order.data.get('segment'), 'segment')
        return BrokerRequest(
            'PUT',
            f'https://api.example-broker.in/orders/{segment}/{order_id}',
            {
                'X-Api-Key': settings['api_key'],
            },
            json_body={
                'quantity': modification.quantity,
                'price': modification.price_number,
                'order_type': modification.order_type,
            },
        )


class CancelAndModifyChecksExample:
    """Runs each cancel and modify check and builds both requests.

    Attributes:
        broker_orders (ExampleBrokerOrders): The broker's order class.
        login (dict): The decoded login.
        settings (dict): The decoded settings.
        stored_order (StoredOrder): An open LIMIT order.
    """

    def __init__(self):
        """Builds the order class, login, settings and stored order.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = ExampleBrokerOrders()
        self.login = {
            'access_token': 'example-token',
        }
        self.settings = {
            'api_key': 'example-api-key',
        }
        self.stored_order = StoredOrder({
            'order': {
                'status': 'OPEN',
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'quantity': 10,
                'price': 2500.0,
            },
            'data': {
                'segment': 'CASH',
            },
        })

    def modify_request(self, body):
        """Validates a modification body.

        Args:
            body (dict): The body.

        Returns:
            ModifyOrderRequest: The validated modification.
        """
        return ModifyOrderRequest(
            body,
            werkzeug.datastructures.MultiDict(),
            [
                'example_broker',
            ],
        )

    def run(self):
        """Prints each check's result and the two requests.

        Returns:
            None: This method returns nothing.
        """
        print(f'Cancel with login and settings: {self.broker_orders.cancel_problem(self.login, self.settings)}')
        print(f'Cancel without settings: {self.broker_orders.cancel_problem(self.login, {})}')
        print(f'Cancel without a login: {self.broker_orders.cancel_problem(None, self.settings)}')
        print(f'Login check beyond the access token: {self.broker_orders.cancel_login_problem(self.login)}')
        print(f'Takes modifications: {self.broker_orders.takes_modifications()}')
        print(f'Modify without a login: {self.broker_orders.modify_problem({}, self.settings)}')
        new_price = self.modify_request({
            'order_id': 'EX1',
            'price': '2505',
        })
        new_validity = self.modify_request({
            'order_id': 'EX1',
            'validity': 'IOC',
        })
        to_stop_loss = self.modify_request({
            'order_id': 'EX1',
            'order_type': 'SL-M',
            'trigger_price': '2480',
        })
        print(f'Change the price: {self.broker_orders.modify_field_problem(new_price)}')
        print(f'Change the validity: {self.broker_orders.modify_field_problem(new_validity)}')
        print(f'Change to SL-M: {self.broker_orders.modify_field_problem(to_stop_loss)}')
        cancel_request = self.broker_orders.build_cancel_request('EX1', self.stored_order, self.login, self.settings)
        print(f'Cancel request: {cancel_request.shown()}')
        modification = OrderModification(new_price, self.stored_order)
        modify_request = self.broker_orders.build_modify_request('EX1', self.stored_order, modification, self.login, self.settings)
        print(f'Modify request: {modify_request.shown()}')
        print(f'stored_value of a held value: {self.broker_orders.stored_value("CASH", "segment")}')
        unready_order = StoredOrder({
            'order': {
                'status': 'OPEN',
            },
            'data': {},
        })
        try:
            self.broker_orders.build_cancel_request('EX2', unready_order, self.login, self.settings)
        except OrderNotReadyError as error:
            print(f'Cancel of an order with no stored segment: HTTP 503, {error}')


if __name__ == '__main__':
    CancelAndModifyChecksExample().run()
