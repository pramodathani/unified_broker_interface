"""Decodes an NSE equity from the text Redis holds for it, and reads the market key a broker's table is looked up by.

The place route reads three strings for an instrument: its identity, every broker's order handle, and, for a currency or commodity derivative, today's contract size decision. `Instrument.decoded` turns them into an `Instrument`. From it the route asks whether orders are taken for the segment at all, whether the instrument is cash or a derivative, whether it is in the securities markets, and the `(exchange, asset class, kind)` key every broker's `MARKETS` table is keyed by.

An equity has no contract size decision, so its trusted size is None and its status `undecided`; neither matters, because securities quantities are counted in shares. The strings below are the shapes `test_runs/order_routes.py` stores. No Redis is used.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/instrument/Instrument/example_1_equity_from_redis_text.py
"""

import json

from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)


class EquityFromRedisTextExample:
    """Decodes RELIANCE on the NSE and prints what the place route reads from it.

    Attributes:
        instrument (Instrument): The decoded instrument.
    """

    def __init__(self):
        """Decodes the instrument from its Redis text.

        Returns:
            None: This method returns nothing.
        """
        identity_text = json.dumps({
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
            'symbol': 'RELIANCE',
        })
        handles_text = json.dumps({
            'zerodha': {
                'broker_token': '738561',
                'order_symbol': 'RELIANCE',
                'lot_size': 1.0,
                'tick_size': 0.1,
            },
            'dhan': {
                'broker_token': '2885',
                'order_symbol': 'RELIANCE',
                'lot_size': 1.0,
                'tick_size': 0.1,
            },
        })
        self.instrument = Instrument.decoded(
            '11111111-1111-5111-8111-000000000001',
            identity_text,
            handles_text,
            None,
        )

    def run(self):
        """Prints the instrument's segment, market and handles.

        Returns:
            None: This method returns nothing.
        """
        print(f'Instrument: {self.instrument.instrument_id}')
        print(f'Segment: {self.instrument.segment} (exchange {self.instrument.exchange}, bare segment {self.instrument.bare_segment})')
        print(f'Tradeable: {self.instrument.is_tradeable()}')
        print(f'Kind: {self.instrument.kind()}')
        print(f'Securities market: {self.instrument.is_securities_market()}')
        print(f'Market key: {self.instrument.market()}')
        print(f'Trusted units per lot: {self.instrument.trusted_units_per_lot()}')
        print(f'Contract size status: {self.instrument.contract_size_status()}')
        print(f'Brokers with a handle: {sorted(self.instrument.handles)}')


if __name__ == '__main__':
    EquityFromRedisTextExample().run()
