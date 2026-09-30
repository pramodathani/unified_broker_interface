"""Builds a lone target for a short position, and shows the exit requests `ExitLegs` refuses.

A one-cancels-other order may name only one exit. This program validates a short sale of 50 units into a `PlaceOrderRequest` and asks `ExitLegs.build` for a target alone, which comes back as a single `BUY` limit order, since buying is what closes a short.

It then shows the three refusals, each a `RefusedRequestError` with HTTP 400: parameters naming no exit at all, a stop given without its limit price, and a price that is not above zero. The stop without a limit is refused deliberately, because defaulting the limit to the trigger would make a stop that does not fill when the price gaps through it, which is exactly when a stop is needed. Nothing is sent to a broker or read from a store.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/exit_legs/ExitLegs/example_2_target_only_and_refusals.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.exit_legs import (
    ExitLegs,
)


class TargetOnlyExample:
    """Builds a target for a short and prints the refusals for bad parameters.

    Attributes:
        exit_legs (ExitLegs): The builder being shown.
        entry (PlaceOrderRequest): The caller's short sale.
        bad_parameters (list): Pairs of (description, parameters) that are refused.
    """

    def __init__(self):
        """Validates the short sale and lists the bad parameters.

        Returns:
            None: This method returns nothing.
        """
        self.exit_legs = ExitLegs()
        self.entry = PlaceOrderRequest({
            'instrument_id': '11111111-1111-5111-8111-000000000004',
            'transaction_type': 'SELL',
            'product': 'NRML',
            'order_type': 'MARKET',
            'quantity': 50,
        })
        self.bad_parameters = [
            (
                'no exit named',
                {
                    'type': 'oco',
                },
            ),
            (
                'stop without its limit',
                {
                    'type': 'oco',
                    'stop_price': '2520.00',
                },
            ),
            (
                'target of zero',
                {
                    'type': 'oco',
                    'target_price': 0,
                },
            ),
        ]

    def run(self):
        """Prints the target built and each refusal.

        Returns:
            None: This method returns nothing.
        """
        parameters = {
            'type': 'oco',
            'target_price': '2450.50',
        }
        legs = self.exit_legs.build(self.entry, parameters, 50)
        print(f'Exits built: {len(legs)}')
        for role, order in legs:
            print(f'{role}: {order.transaction_type} {order.quantity} {order.product} {order.order_type} price {order.price_text} trigger {order.trigger_price_text}')
        for description, bad in self.bad_parameters:
            try:
                self.exit_legs.build(self.entry, bad, 50)
            except RefusedRequestError as error:
                print(f'{description}: refused with {error.status}: {error.body["error"]}')


if __name__ == '__main__':
    TargetOnlyExample().run()
