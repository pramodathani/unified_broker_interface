"""Gives five instruments to three brokers and shows the rules that decide each one.

`allocate` takes each instrument's carriers - the brokers able to stream it, with the member each would subscribe - and gives it to one of them. Instruments with fewer carriers go first, so an instrument only one broker carries gets that broker's room before an instrument with alternatives can take it. Among several carriers with room the lowest `preference` wins. The capacities here are set by hand rather than read from the table, so the program needs no database, no Redis, no network and no broker login.

Notice that the option only Stoxkart carries takes Stoxkart's single slot first, so the gold future Stoxkart and Dhan both carry goes to Dhan. The three equities Zerodha and Dhan both carry go to Zerodha, whose preference is lower, until Zerodha's two slots are full, and TCS then goes to Dhan.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/utilities/allocation/QuoteSubscriptionAllocation/example_1_choosing_a_broker.py
"""

import datetime
import json
import logging

from unified_broker_interface.utilities.quote_subscriptions.utilities.allocation import (
    QuoteCapacity,
    QuoteSubscriptionAllocation,
)


class ChoosingABrokerExample:
    """Allocates hand-built carriers and prints the shares and the summary.

    Attributes:
        allocation (QuoteSubscriptionAllocation): The allocation being shown.
        carriers (dict): Each instrument id to its sort key and carriers.
    """

    def __init__(self):
        """Sets the capacities and builds the carriers.

        Returns:
            None: This method returns nothing.
        """
        self.allocation = QuoteSubscriptionAllocation(None, None, logging.getLogger('example'))
        self.allocation.capacities = {
            'zerodha': QuoteCapacity('zerodha', 1, 2, 1),
            'dhan': QuoteCapacity('dhan', 1, 2, 3),
            'stoxkart': QuoteCapacity('stoxkart', 1, 1, 5),
        }
        self.allocation.mapping_date = datetime.date(2026, 10, 27)
        self.carriers = {
            'reliance': {
                'order': (0, datetime.date.max, 'reliance'),
                'members': {
                    'zerodha': '738561',
                    'dhan': 'NSE_EQ:2885',
                },
            },
            'gold_future': {
                'order': (1, datetime.date(2026, 12, 5), 'gold_future'),
                'members': {
                    'dhan': 'MCX_COMM:565899',
                    'stoxkart': 'MCX:565899',
                },
            },
            'odd_option': {
                'order': (2, datetime.date(2026, 11, 24), 'odd_option'),
                'members': {
                    'stoxkart': 'NFO:77001',
                },
            },
            'infy': {
                'order': (0, datetime.date.max, 'infy'),
                'members': {
                    'zerodha': '408065',
                    'dhan': 'NSE_EQ:1594',
                },
            },
            'tcs': {
                'order': (0, datetime.date.max, 'tcs'),
                'members': {
                    'zerodha': '2953217',
                    'dhan': 'NSE_EQ:11536',
                },
            },
        }

    def run(self):
        """Allocates and prints each broker's members and the summary's counts.

        Returns:
            None: This method returns nothing.
        """
        assigned = self.allocation.allocate(self.carriers)
        for broker, members in assigned.items():
            print(f'{broker}: {members}')
        summary = self.allocation.summary()
        del summary['written_at']
        print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    ChoosingABrokerExample().run()
