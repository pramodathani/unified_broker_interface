"""Settles a reset place-order request from Noren's order book: which order in the book is the request's, and which are not.

On 21 October 2026 Flattrade reset the connection of a protective stop's sell, so UBI could not tell whether the order had been placed. `NorenOrders.find_placed_order` now reads Noren's `OrderBook` on a new connection and looks for the order. This program does the same matching offline: it builds the `OrderBook` request from the place request, with the same account and session token, and checks four orders a book could hold against the request. Only an order with the same exchange, symbol, side, product, order type, quantity and price, received no earlier than five seconds before the request was sent, counts as the request's.

The times are fixed, so the output is the same on every run, and nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/noren/NorenOrders/example_3_finding_an_order_after_a_reset.py
"""

import datetime
import json
import zoneinfo

from unified_broker_interface.utilities.broker_orders.noren import NorenOrders
from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class ExampleNorenOrders(NorenOrders):
    """A made-up broker on the Noren platform."""

    BROKER_NAME = 'example_noren'
    BASE_URL = 'https://api.example-noren.in/NorenWClientTP'
    ACCOUNT_SETTINGS_FIELD = 'client_code'


class FindingAnOrderAfterAResetExample:
    """Matches four book rows against one reset sell.

    Attributes:
        broker_orders (ExampleNorenOrders): The made-up broker's order class.
        fields (dict): The sell's `jData` fields.
        sent_at_epoch (float): When the sell was sent, 11:33:48 on 21 October 2026 in India.
    """

    def __init__(self):
        """Builds the order class, the sell and its sending time.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = ExampleNorenOrders()
        self.fields = {
            'uid': 'EN00001',
            'actid': 'EN00001',
            'exch': 'NFO',
            'tsym': 'NIFTY23NOV26C22900',
            'qty': '65',
            'prc': '434.3',
            'trgprc': None,
            'prd': 'M',
            'trantype': 'S',
            'prctyp': 'LMT',
            'ret': 'DAY',
        }
        sent_at = datetime.datetime(2026, 10, 21, 11, 33, 48, tzinfo=INDIA)
        self.sent_at_epoch = sent_at.timestamp()

    def row(self, price, received):
        """Builds one order as Noren's book lists it.

        Args:
            price (str): The order's limit price.
            received (str): When Noren received it, as `HH:MM:SS`.

        Returns:
            dict: The row.
        """
        row = dict(self.fields)
        row['prc'] = price
        row['norentm'] = f'{received} 21-10-2026'
        row['norenordno'] = f'26102100{received.replace(":", "")}'
        return row

    def run(self):
        """Builds the book request, then matches each row and prints the verdict.

        Returns:
            None: This method returns nothing.
        """
        place_request = BrokerRequest(
            'POST',
            f'{self.broker_orders.BASE_URL}/PlaceOrder',
            {},
            data=self.broker_orders.encoded_body(self.fields, {'access_token': 'example-session-token'}),
            shown_form=self.fields,
        )
        book_request = self.broker_orders.order_book_request(place_request)
        print('Order book request:')
        print(json.dumps(book_request.shown(), indent=2, sort_keys=True))
        print(f'Its body: {book_request.data}')
        rows = [
            ('the same sell, received the same second', self.row('434.3', '11:33:48')),
            ('the same sell, received a minute earlier', self.row('434.3', '11:32:48')),
            ('a sell at another price', self.row('440.0', '11:33:49')),
            ('the same sell, received 3 s before it was sent', self.row('434.3', '11:33:45')),
        ]
        for label, row in rows:
            matched = self.broker_orders.matches_request(row, self.fields, self.sent_at_epoch)
            print(f'{label}: {"matches" if matched else "does not match"}')


if __name__ == '__main__':
    FindingAnOrderAfterAResetExample().run()
