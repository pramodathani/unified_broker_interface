"""Shows which kind of order an intent asks the engine to run, for five different request bodies.

An API worker builds an `OrderIntent` for every order it accepts and writes it to the engine's stream. The intent reads the `synthetic` object of the body to learn which kind of order to run, and when the virtual order book is switched on (`hold_limits=True`) it also decides whether a plain limit order is held in that book instead of being sent at once.

The program builds one intent for each body and prints the kind it chose, and it also calls `is_holdable` and `is_after_market` directly so the reasons are visible. Notice that only the ordinary day limit order becomes `virtual_limit`: the market order, the `IOC` order and the after-market order stay `simple`, and a body that names its own type keeps it.

Nothing here touches Redis or a broker, because building an intent only reads the body.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_intent/OrderIntent/example_1_which_orders_are_held.py
"""

from unified_broker_interface.utilities.order_engine.utilities.order_intent import (
    OrderIntent,
)


class WhichOrdersAreHeldExample:
    """Builds intents for several bodies with the virtual order book switched on.

    Attributes:
        bodies (list): Pairs of (label, request body) to build intents for.
    """

    def __init__(self):
        """Prepares the request bodies.

        Returns:
            None: This method returns nothing.
        """
        self.bodies = [
            (
                'day limit',
                {
                    'transaction_type': 'BUY',
                    'order_type': 'LIMIT',
                    'price': 1520.5,
                    'quantity': 10,
                },
            ),
            (
                'market',
                {
                    'transaction_type': 'BUY',
                    'order_type': 'MARKET',
                    'quantity': 10,
                },
            ),
            (
                'IOC limit',
                {
                    'transaction_type': 'SELL',
                    'order_type': 'LIMIT',
                    'price': 1519.0,
                    'validity': 'IOC',
                    'quantity': 10,
                },
            ),
            (
                'after-market limit',
                {
                    'transaction_type': 'BUY',
                    'order_type': 'LIMIT',
                    'price': 1500.0,
                    'after_market': 'yes',
                    'quantity': 10,
                },
            ),
            (
                'named trailing stop',
                {
                    'transaction_type': 'SELL',
                    'order_type': 'LIMIT',
                    'price': 1500.0,
                    'quantity': 10,
                    'synthetic': {
                        'type': 'trailing_stop',
                        'trail': 5,
                    },
                },
            ),
        ]

    def run(self):
        """Prints the kind of order each body becomes.

        Returns:
            None: This method returns nothing.
        """
        for label, body in self.bodies:
            intent = OrderIntent(body, 'NSE:INFY', 10, hold_limits=True)
            holdable = intent.is_holdable(body)
            after_market = intent.is_after_market(body)
            print(f'{label}: type={intent.synthetic_type} holdable={holdable} after_market={after_market}')
        plain_intent = OrderIntent(self.bodies[0][1], 'NSE:INFY', 10)
        print(f'day limit without the virtual book: {plain_intent.read_synthetic_type(plain_intent.body, False)}')


if __name__ == '__main__':
    WhichOrdersAreHeldExample().run()
