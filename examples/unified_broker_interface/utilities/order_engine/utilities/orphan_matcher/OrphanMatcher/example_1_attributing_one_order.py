"""Finds the one order in a broker's book that a crashed engine sent, and attributes it to its leg.

When the engine crashes between recording a leg as `sending` and hearing the broker's answer, the leg has no broker order id, yet an order may be live at the broker. On restart, `OrphanMatcher.attribute` compares the leg with every unclaimed order in that broker's book and attributes it only when exactly one order agrees on every field the engine sent, placed within a few seconds of the request.

The book here is written by hand in the shape the order pollers store it: one entry per broker order id, with the normalized order under `order`. It holds the true order, an order for another instrument, an identical order placed ten minutes earlier, and an identical order already claimed by another leg. The program prints the verdict and then checks each order with `matches`, `identifier_agrees` and `timestamp_agrees` to show why only one survives. `now` is pinned to ten seconds after the book was read, so the book counts as fresh on every run.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/orphan_matcher/OrphanMatcher/example_1_attributing_one_order.py
"""

import logging

from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)
from unified_broker_interface.utilities.order_engine.utilities.orphan_matcher import (
    OrphanMatcher,
)


class AttributingOneOrderExample:
    """Attributes a leg left in `sending` to the single matching order in the book.

    Attributes:
        matcher (OrphanMatcher): The matcher being shown.
        leg (OrderLeg): The leg found in `sending` after the crash.
        book (dict): The broker's order book, by broker order id.
        claimed_order_ids (set): Broker order ids that already belong to another leg.
    """

    def __init__(self):
        """Builds the leg and a book of four orders.

        Returns:
            None: This method returns nothing.
        """
        self.matcher = OrphanMatcher(logging.getLogger('example'))
        self.leg = OrderLeg('parent-a:1', 'entry')
        self.leg.state = 'sending'
        self.leg.broker = 'zerodha'
        self.leg.identifier_sent = 'INFY'
        self.leg.transaction_type = 'BUY'
        self.leg.product = 'INTRADAY'
        self.leg.order_type = 'LIMIT'
        self.leg.validity = 'DAY'
        self.leg.quantity = 10
        self.leg.price = 1520.5
        self.leg.tag_sent = 'swing42'
        self.leg.requested_at = '2026-09-30T09:20:01+05:30'
        self.book = {
            '250930000123456': self.entry('INFY', '2026-09-30T09:20:01.4+05:30'),
            '250930000123460': self.entry('TCS', '2026-09-30T09:20:01.6+05:30'),
            '250930000120001': self.entry('INFY', '2026-09-30T09:10:00+05:30'),
            '250930000123470': self.entry('INFY', '2026-09-30T09:20:02+05:30'),
        }
        self.claimed_order_ids = {
            '250930000123470',
        }

    def entry(self, tradingsymbol, order_timestamp):
        """Builds one order book entry that agrees with the leg except where told otherwise.

        Args:
            tradingsymbol (str): The order's trading symbol.
            order_timestamp (str): When the broker says the order was placed.

        Returns:
            dict: The entry, with the normalized order under `order`.
        """
        return {
            'order': {
                'tradingsymbol': tradingsymbol,
                'instrument_token': None,
                'transaction_type': 'BUY',
                'product': 'INTRADAY',
                'order_type': 'LIMIT',
                'validity': 'DAY',
                'tag': 'swing42',
                'quantity': 10,
                'price': 1520.5,
                'trigger_price': None,
                'order_timestamp': order_timestamp,
            },
        }

    def run(self):
        """Prints the verdict and each order's comparison.

        Returns:
            None: This method returns nothing.
        """
        polled_at = 1790743800.0
        verdict = self.matcher.attribute(self.leg, self.book, polled_at, self.claimed_order_ids, now=polled_at + 10)
        print(f'Outcome: {verdict["outcome"]}')
        print(f'Broker order id: {verdict["broker_order_id"]}')
        print(f'Why: {verdict["status_message"]}')
        for broker_order_id, entry in self.book.items():
            order = entry['order']
            claimed = broker_order_id in self.claimed_order_ids
            instrument = self.matcher.identifier_agrees(self.leg, order)
            timing = self.matcher.timestamp_agrees(self.leg, order)
            matched = self.matcher.matches(self.leg, order)
            print(f'{broker_order_id}: claimed={claimed} instrument={instrument} timing={timing} matches={matched}')


if __name__ == '__main__':
    AttributingOneOrderExample().run()
