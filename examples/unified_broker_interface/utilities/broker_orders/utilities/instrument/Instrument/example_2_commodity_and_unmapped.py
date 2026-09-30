"""Reads a crude oil future's trusted contract size, and shows what happens to an instrument that is not tradeable or not mapped.

A currency or commodity derivative is counted in lots whose size the brokers do not always agree on, so the daily mapping decides a trusted size each morning. `trusted_units_per_lot` gives it only when the decision says the contract is tradeable; otherwise the order is refused, and `contract_size_status` gives the reason for the message.

An index is mapped but cannot be traded, so `is_tradeable` is False. An instrument whose identity Redis does not hold makes `decoded` raise `RefusedRequestError` with HTTP 404. The decision texts are shapes `test_runs/order_routes.py` stores; no Redis is used.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/instrument/Instrument/example_2_commodity_and_unmapped.py
"""

import json

from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)


class CommodityAndUnmappedExample:
    """Decodes a crude oil future under two decisions, an index, and a missing instrument.

    Attributes:
        identity_text (str): The crude oil future's identity as Redis holds it.
        handles_text (str): Its order handles as Redis holds them.
    """

    def __init__(self):
        """Builds the future's identity and handles.

        Returns:
            None: This method returns nothing.
        """
        self.identity_text = json.dumps({
            'exchange': 'mcx',
            'segment': 'mcx_commodity_futures',
            'shape': 'future',
            'underlying_symbol': 'CRUDEOIL',
            'expiry_date': '2026-10-19',
        })
        self.handles_text = json.dumps({
            'zerodha': {
                'broker_token': '569900',
                'order_symbol': 'CRUDEOIL26OCTFUT',
                'lot_size': 1.0,
                'tick_size': 1.0,
            },
        })

    def show_future(self, label, contract_size_text):
        """Decodes the future under one contract size decision and prints what it gives.

        Args:
            label (str): What the decision is.
            contract_size_text (str): The decision as Redis holds it.

        Returns:
            None: This method returns nothing.
        """
        instrument = Instrument.decoded(
            '22222222-2222-5222-8222-000000000001',
            self.identity_text,
            self.handles_text,
            contract_size_text,
        )
        print(f'{label}: market={instrument.market()}, securities={instrument.is_securities_market()}, units per lot={instrument.trusted_units_per_lot()}, status={instrument.contract_size_status()}')

    def run(self):
        """Prints the future under two decisions, then the index and the missing instrument.

        Returns:
            None: This method returns nothing.
        """
        decided = json.dumps({
            'units_per_lot': '100',
            'status': 'confirmed',
            'tradeable': True,
        })
        disputed = json.dumps({
            'units_per_lot': None,
            'status': 'conflict',
            'tradeable': False,
        })
        self.show_future('Decided', decided)
        self.show_future('Disputed', disputed)
        index = Instrument(
            '33333333-3333-5333-8333-000000000001',
            {
                'segment': 'nse_indices',
            },
            {},
        )
        print(f'NIFTY 50 index tradeable: {index.is_tradeable()}')
        try:
            Instrument.decoded('44444444-4444-5444-8444-000000000001', None, None, None)
        except RefusedRequestError as error:
            print(f'Missing instrument: HTTP {error.status}, {error.body}')


if __name__ == '__main__':
    CommodityAndUnmappedExample().run()
