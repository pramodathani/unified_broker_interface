"""Walks through the steps `holdings` takes, one method at a time, for a positions document holding one call at two brokers.

`holdings` decodes the unified positions document, reads when it was written, keeps only the brokers whose positions are `ok`, and reads each broker's share as a decimal. This program calls each of those steps itself, with a scripted document, so each can be seen on its own and it needs nothing running.

Notice that Zerodha's share is dropped from the holdings, because its positions are `stale`, and that a share which cannot be read counts as zero rather than as a holding.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/closing_positions/ClosingPositions/example_3_the_steps_inside_holdings.py
"""

import datetime
import json

from unified_broker_interface.utilities.broker_selection.utilities.closing_positions import (
    ClosingPositions,
)


class TheStepsInsideHoldingsExample:
    """Calls each step of `holdings` and prints what it returns.

    Attributes:
        closing_positions (ClosingPositions): The reader, trusting a document up to five seconds old.
        positions_text (str): The scripted positions document.
    """

    def __init__(self):
        """Builds the reader and the document.

        Returns:
            None: This method returns nothing.
        """
        self.closing_positions = ClosingPositions(5)
        self.positions_text = json.dumps({
            'net': [
                {
                    'instrument_id': 'nifty-2026-10-27-22600-ce',
                    'product': 'carry',
                    'quantity': 130.0,
                    'by_broker': {
                        'flattrade': 65.0,
                        'zerodha': 65.0,
                    },
                },
            ],
            'brokers': [
                {
                    'broker': 'flattrade',
                    'status': 'ok',
                },
                {
                    'broker': 'zerodha',
                    'status': 'stale',
                },
            ],
            'as_of': '2026-10-07T11:41:23',
        })

    def run(self):
        """Prints the result of each step, then of `holdings` as a whole.

        Returns:
            None: This method returns nothing.
        """
        document = self.closing_positions.document(self.positions_text)
        print(f'document keys: {sorted(document)}')
        print(f'document of an empty reply: {self.closing_positions.document(None)}')
        print(f'read_time: {self.closing_positions.read_time(document["as_of"])}')
        print(f'read_time of a time in the wrong form: {self.closing_positions.read_time("11:41")}')
        print(f'trusted_brokers: {sorted(self.closing_positions.trusted_brokers(document))}')
        print(f'decimal_or_zero of 65.0: {self.closing_positions.decimal_or_zero(65.0)}')
        print(f'decimal_or_zero of "n/a": {self.closing_positions.decimal_or_zero("n/a")}')
        now = datetime.datetime(2026, 10, 7, 11, 41, 24)
        print(f'holdings: {self.closing_positions.holdings(self.positions_text, now)}')


if __name__ == '__main__':
    TheStepsInsideHoldingsExample().run()
