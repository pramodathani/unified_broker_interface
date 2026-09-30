"""Validates an order whose price and quantity are worked out by the order engine, and calls the readers behind those references.

Instead of a price, a caller may give a `price_reference`, such as "the second best offer plus a tenth of a per cent", and instead of a quantity a `quantity_reference`, such as "whatever closes my position". `PlaceOrderRequest` only checks their shape; the order engine resolves them from the live quote and the position when it sends the order.

The program validates such an order, then calls each reader on its own: `reference_kind`, `parse_level`, `parse_signed_number`, `parse_signed_whole_number`, `parse_quantities`, `check_prices_fit_the_order_type` and `parse_tag`, including the messages they refuse bad values with. Nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/place_order_request/PlaceOrderRequest/example_2_price_and_quantity_references.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)


class PriceAndQuantityReferencesExample:
    """Validates an order with references and exercises each reader.

    Attributes:
        order (PlaceOrderRequest): The validated order.
    """

    def __init__(self):
        """Validates a LIMIT sell that closes the MIS position at the second best offer.

        Returns:
            None: This method returns nothing.
        """
        self.order = PlaceOrderRequest({
            'instrument_id': '11111111-1111-5111-8111-000000000001',
            'transaction_type': 'SELL',
            'product': 'MIS',
            'order_type': 'LIMIT',
            'price_reference': {
                'kind': 'offer_level',
                'level': 2,
                'buffer_percent': '0.1',
                'offset_ticks': -1,
            },
            'quantity_reference': {
                'kind': 'liquidate_position',
                'product': 'MIS',
            },
        })

    def run(self):
        """Prints the references, then each reader's result and refusal.

        Returns:
            None: This method returns nothing.
        """
        print(f'Price reference: {self.order.price_reference}')
        print(f'Quantity reference: {self.order.quantity_reference}')
        print(f'Quantity until the engine resolves it: {self.order.quantity}')
        mid_reference = {
            'price_reference': {
                'kind': 'MID',
                'offset_percent': '-0.05',
            },
        }
        print(f'parse_price_reference mid: {self.order.parse_price_reference(mid_reference)}')
        add_reference = {
            'quantity_reference': {
                'kind': 'add_to_position',
            },
        }
        print(f'parse_quantity_reference add: {self.order.parse_quantity_reference(add_reference)}')
        vwap_reference = {
            'kind': ' VWAP ',
        }
        print(f'reference_kind: {self.order.reference_kind(vwap_reference, "price_reference", PlaceOrderRequest.PRICE_REFERENCE_KINDS)}')
        print(f'parse_level with none given: {self.order.parse_level({})}')
        offsets = {
            'offset_percent': '-0.25',
            'offset_ticks': '-3',
        }
        print(f'parse_signed_number: {self.order.parse_signed_number(offsets, "offset_percent")!r}')
        print(f'parse_signed_whole_number: {self.order.parse_signed_whole_number(offsets, "offset_ticks")}')
        print(f'parse_tag: {self.order.parse_tag(" exit01 ")!r}')
        self.order.parse_quantities({
            'quantity': 40,
            'disclosed_quantity': 10,
        })
        print(f'parse_quantities: quantity={self.order.quantity}, disclosed={self.order.disclosed_quantity}')
        self.order.check_prices_fit_the_order_type()
        print('check_prices_fit_the_order_type: a LIMIT order with a price reference passes')
        try:
            self.order.parse_level({
                'level': 6,
            })
        except InvalidOrderError as error:
            print(f'Level 6: {error}')
        try:
            self.order.reference_kind(
                {
                    'kind': 'best',
                },
                'price_reference',
                PlaceOrderRequest.PRICE_REFERENCE_KINDS,
            )
        except InvalidOrderError as error:
            print(f'Kind unknown: {error}')
        try:
            self.order.parse_signed_whole_number(
                {
                    'offset_ticks': '1.5',
                },
                'offset_ticks',
            )
        except InvalidOrderError as error:
            print(f'Offset ticks 1.5: {error}')
        try:
            self.order.parse_signed_number(
                {
                    'buffer_percent': 'lots',
                },
                'buffer_percent',
            )
        except InvalidOrderError as error:
            print(f'Buffer not a number: {error}')
        try:
            self.order.parse_tag('exit 01')
        except InvalidOrderError as error:
            print(f'Tag with a space: {error}')
        try:
            self.order.parse_quantities({
                'quantity': 5,
                'disclosed_quantity': 10,
            })
        except InvalidOrderError as error:
            print(f'Disclosed above quantity: {error}')
        self.order.price_reference = None
        try:
            self.order.check_prices_fit_the_order_type()
        except InvalidOrderError as error:
            print(f'LIMIT without a price: {error}')

if __name__ == '__main__':
    PriceAndQuantityReferencesExample().run()
