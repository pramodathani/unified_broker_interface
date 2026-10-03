"""Reads plans asked to hold their orders in the virtual order book, and prints which orders are held, which are left alone and which are refused.

`hold_limits` is read from an order itself, or else from the request, the `hold_limits` beside the plan, which the reader is given. A held order gets a `limit_marketable` condition added to its trigger, so it is sent only once the other side of the book reaches its price. The request's value holds only an order that would rest at the body's own limit price: it leaves a market order alone, does not reach a follow-on order in a Then join's child, and never holds a leg of a Together join that checks the group's margin. When an order asks for itself and cannot be held, the plan is refused with the reason. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/plan_reader/PlanReader/example_3_holding_orders_until_the_market_reaches_them.py
"""

from unified_broker_interface.utilities.order_engine.utilities.plan_reader import (
    PlanReader,
)


class HoldingOrdersExample:
    """Reads six plans with a limit or a market body and prints each order's trigger."""

    def body(self, order_type):
        """A buy of ten at 1000, as a limit or a market order.

        Args:
            order_type (str): `LIMIT` or `MARKET`.

        Returns:
            dict: The body.
        """
        body = {
            'transaction_type': 'BUY',
            'order_type': order_type,
            'quantity': 10,
            'validity': 'DAY',
        }
        if order_type == 'LIMIT':
            body['price'] = 1000
        return body

    def show(self, label, plan, order_type, hold_limits):
        """Reads one plan and prints every order's trigger, or the problems.

        Args:
            label (str): What the case shows.
            plan (dict): The plan.
            order_type (str): The body's order type.
            hold_limits (object): The request's `hold_limits`, or None.

        Returns:
            None: This method returns nothing.
        """
        reader = PlanReader('BUY', self.body(order_type), hold_limits)
        root = reader.read(plan)
        print(f'{label}:')
        if root is None:
            for problem in reader.problems:
                print(f'  refused at {problem["path"]}, {problem["rule"]}: {problem["message"]}')
            return
        for part in root.order_parts():
            trigger = 'at_once'
            if part.trigger is not None:
                trigger = part.trigger.described()
            print(f'  {part.path}: {trigger}')

    def run(self):
        """Reads the six plans.

        Returns:
            None: This method returns nothing.
        """
        plain = {
            'order': {},
        }
        self.show('the request holds a limit order', plain, 'LIMIT', True)
        self.show('the request leaves a market order alone', plain, 'MARKET', True)
        self.show('the request says nothing', plain, 'LIMIT', None)
        self.show(
            'the order asks to hold a market order',
            {
                'order': {
                    'hold_limits': True,
                },
            },
            'MARKET',
            None,
        )
        self.show(
            'the request holds an entry, not its follow-on order',
            {
                'then': {
                    'first': {
                        'order': {
                            'presets': [
                                {
                                    'scheduled': {
                                        'at_time': '10:00',
                                    },
                                },
                            ],
                        },
                    },
                    'each_fill': {
                        'order': {
                            'side': 'sell',
                        },
                    },
                },
            },
            'LIMIT',
            True,
        )
        self.show(
            'the request reaches no leg of a margin-checked group',
            {
                'together': {
                    'children': [
                        {
                            'order': {},
                        },
                        {
                            'order': {
                                'transaction_type': 'SELL',
                            },
                        },
                    ],
                },
            },
            'LIMIT',
            True,
        )


if __name__ == '__main__':
    HoldingOrdersExample().run()
