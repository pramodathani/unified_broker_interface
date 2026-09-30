"""Shows the three ways the matcher refuses to attribute an orphaned leg, and the small helpers it compares with.

`OrphanMatcher` is deliberately unwilling. If the broker's book was last read more than a minute ago, it does not compare at all. If no order matches, or more than one does, it abandons the leg, and the engine parks the parent in `failed` for a person to look at, because hanging a stop on the wrong position is worse than admitting it does not know.

The program runs one leg against a stale book, an empty book, and a book holding two identical orders, and prints each verdict. It then calls the helpers the comparison is built from: `book_is_fresh`, `candidates`, `abandoned`, and the conversions `moment`, `text`, `whole` and `rounded`, which make `'10'` equal `10.0` and treat an empty tag like a missing one. Every time is pinned, so the output is the same on every run.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/orphan_matcher/OrphanMatcher/example_2_refusing_to_guess.py
"""

import logging

from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)
from unified_broker_interface.utilities.order_engine.utilities.orphan_matcher import (
    OrphanMatcher,
)


class RefusingToGuessExample:
    """Runs one orphaned leg against books it cannot safely match.

    Attributes:
        matcher (OrphanMatcher): The matcher being shown.
        leg (OrderLeg): A stop-loss leg found in `sending`.
        order (dict): An order in the book that agrees with the leg.
        polled_at (float): When the book was read, as an epoch.
    """

    def __init__(self):
        """Builds the leg and a matching order.

        Returns:
            None: This method returns nothing.
        """
        self.matcher = OrphanMatcher(logging.getLogger('example'))
        self.leg = OrderLeg('parent-b:2', 'stop')
        self.leg.state = 'sending'
        self.leg.identifier_sent = '3045'
        self.leg.transaction_type = 'SELL'
        self.leg.product = 'INTRADAY'
        self.leg.order_type = 'SL-M'
        self.leg.validity = 'DAY'
        self.leg.quantity = 50
        self.leg.trigger_price = 801.5
        self.leg.tag_sent = ''
        self.leg.requested_at = '2026-09-30T10:05:00+05:30'
        self.order = {
            'instrument_token': '3045',
            'tradingsymbol': 'SBIN-EQ',
            'transaction_type': 'SELL',
            'product': 'INTRADAY',
            'order_type': 'SL-M',
            'validity': 'DAY',
            'tag': None,
            'quantity': '50',
            'price': None,
            'trigger_price': '801.50',
            'order_timestamp': None,
        }
        self.polled_at = 1790744100.0

    def show(self, label, book, now):
        """Prints the verdict for one book.

        Args:
            label (str): What the book is.
            book (dict): The order book.
            now (float): The moment to reckon from.

        Returns:
            None: This method returns nothing.
        """
        verdict = self.matcher.attribute(self.leg, book, self.polled_at, set(), now=now)
        print(f'{label}: {verdict["outcome"]}, candidates={verdict["candidates"]}')
        print(f'  {verdict["status_message"]}')

    def run(self):
        """Prints the three refusals and the helpers' answers.

        Returns:
            None: This method returns nothing.
        """
        twin_book = {
            '1102509300000002': {
                'order': self.order,
            },
            '1102509300000001': {
                'order': dict(self.order),
            },
        }
        self.show('Book read 90 seconds ago', twin_book, self.polled_at + 90)
        self.show('Empty book', {}, self.polled_at + 5)
        self.show('Two identical orders', twin_book, self.polled_at + 5)
        print(f'Fresh after 60 seconds: {self.matcher.book_is_fresh(self.polled_at, self.polled_at + 60)}')
        print(f'Fresh when never read: {self.matcher.book_is_fresh(None, self.polled_at)}')
        claimed_order_ids = {
            '1102509300000001',
        }
        print(f'Candidates with one claimed: {self.matcher.candidates(self.leg, twin_book, claimed_order_ids)}')
        print(f'Abandoned by hand: {self.matcher.abandoned("checked by a person", [])}')
        print(f'moment of an IST time: {self.matcher.moment("2026-09-30T10:05:00+05:30")}')
        print(f'moment of rubbish: {self.matcher.moment("yesterday")}')
        print(f'text of an empty tag: {self.matcher.text("")}')
        print(f'whole of "50": {self.matcher.whole("50")}, of "fifty": {self.matcher.whole("fifty")}')
        print(f'rounded of "801.50": {self.matcher.rounded("801.50")}, of None: {self.matcher.rounded(None)}')


if __name__ == '__main__':
    RefusingToGuessExample().run()
