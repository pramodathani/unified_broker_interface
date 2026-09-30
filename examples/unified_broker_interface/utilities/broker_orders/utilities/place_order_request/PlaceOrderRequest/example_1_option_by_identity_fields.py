"""Validates an order for a NIFTY call option named by its identity fields, and runs the checks made once a broker is chosen.

A caller can name an instrument by its id, or by exchange, segment and the segment's identity fields. For an option those are the underlying, the expiry, the strike and the option type. `PlaceOrderRequest` checks them and builds the catalogue segment and member prefix the route searches today's catalogue with. The pieces come from `security_prefix`, `expiring_prefix` and `option_suffix`, which the program also calls on their own, and `parse_instrument` which puts them together.

After a broker is chosen, the route checks the quantity against that broker's lot size and the price against the tick size most brokers agree on, and `with_quantities` gives a copy carrying a broker's own quantities. `contract_lot_problem` is the same kind of check for a currency or commodity contract's trusted size. The handles are shapes `test_runs/order_routes.py` builds. Nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/place_order_request/PlaceOrderRequest/example_1_option_by_identity_fields.py
"""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)


class OptionByIdentityFieldsExample:
    """Validates the option order and prints the catalogue search and the checks.

    Attributes:
        body (dict): The caller's body.
        order (PlaceOrderRequest): The validated order.
        handles (dict): Two brokers' order handles for the option.
    """

    def __init__(self):
        """Validates a LIMIT buy of two lots of the option.

        Returns:
            None: This method returns nothing.
        """
        self.body = {
            'exchange': 'NSE',
            'segment': 'nse_equity_index_options',
            'underlying_symbol': 'nifty',
            'expiry_date': '2026-10-27',
            'strike_price': '25000',
            'option_type': 'ce',
            'transaction_type': 'buy',
            'product': 'NRML',
            'order_type': 'LIMIT',
            'price': '120.05',
            'quantity': 150,
            'tag': 'straddle01',
        }
        self.order = PlaceOrderRequest(self.body)
        self.handles = {
            'zerodha': {
                'order_symbol': 'NIFTY26O2725000CE',
                'lot_size': 75.0,
                'tick_size': 0.05,
            },
            'dhan': {
                'broker_token': '43210',
                'lot_size': 75.0,
                'tick_size': 0.05,
            },
        }

    def run(self):
        """Prints the validated order, its catalogue search and the broker checks.

        Returns:
            None: This method returns nothing.
        """
        print(f'{self.order.transaction_type} {self.order.quantity} {self.order.product} {self.order.order_type} at {self.order.price_text}, tag {self.order.tag}')
        print(f'Catalogue segment: {self.order.catalogue_segment}')
        print(f'Catalogue prefix: {self.order.catalogue_prefix}')
        security_body = {
            'symbol': 'reliance',
        }
        print(f'  security_prefix of RELIANCE: {self.order.security_prefix(security_body)}')
        print(f'  expiring_prefix: {self.order.expiring_prefix(self.body, "option")}')
        print(f'  option_suffix: {self.order.option_suffix(self.body)}')
        by_id = PlaceOrderRequest({
            'instrument_id': '11111111-1111-5111-8111-000000000001',
            'transaction_type': 'SELL',
            'product': 'CNC',
            'order_type': 'MARKET',
            'quantity': 1,
        })
        by_id.parse_instrument({
            'instrument_id': '  22222222-2222-5222-8222-000000000001 ',
        })
        print(f'parse_instrument with an id: instrument_id={by_id.instrument_id}, catalogue_segment={by_id.catalogue_segment}')
        print(f'Lot check at Zerodha: {self.order.lot_size_problem(self.handles["zerodha"])}')
        print(f'Tick check: {self.order.tick_size_problem(self.handles)}')
        print(f'Contract check against 100 units a lot: {self.order.contract_lot_problem(decimal.Decimal("100"))}')
        in_lots = self.order.with_quantities(2, 0)
        print(f'Copy for a broker counting lots: quantity={in_lots.quantity}; original still {self.order.quantity}')


if __name__ == '__main__':
    OptionByIdentityFieldsExample().run()
