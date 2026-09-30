"""Reads what an order type needs about the market before it builds a leg: the instrument, its quote, the positions, broker quantities and extra broker attributes.

An order with a price reference, such as "the best bid plus one tick", needs the live quote, and an order with a quantity reference, such as "close the whole position", needs the positions. `market_context` reads the mapping marker and then the instrument, the quote and the positions together, so it costs two round trips. The instrument's catalogue entry is kept in the engine's own cache, so a second read of the same instrument still costs two round trips but its second one carries only the quote and the positions, not the three catalogue reads.

`broker_quantity` converts a quantity in units into what one broker's request carries. For Infosys, a security, the number is unchanged. For a crude oil future on MCX, whose contract size this morning's decision trusts as 100 barrels a lot, 300 barrels become 3 of Zerodha's lots; 250 barrels is not a whole number of lots and is refused with HTTP 400, and a gold option whose contract size is in conflict today is refused with HTTP 503. `broker_attributes` reads the brokers' extra fields for an instrument, such as the exchange freeze quantity that the freeze slicer compares a leg against; a broker that publishes none is simply missing from the answer.

Redis is the in-memory `FakeRedis` from `test_runs/redis_stand_ins.py`, filled with three mapped instruments, a live quote, the net positions and one instrument's extra attributes. It counts round trips, which the program prints. No broker is called, because nothing here sends an order.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_placement/EnginePlacement/example_4_market_context_and_quantities.py
"""

import json
import logging

from test_runs.redis_stand_ins import FakeRedis
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_placement import (
    EnginePlacement,
)
from utilities.configurations import api_configuration

MAPPING_DATE = '2026-09-30'
PREFIX = f'unified:catalogue:{MAPPING_DATE}:'
INFOSYS_ID = '6d1f3a52-8b0e-5c47-9a21-3e4f5b6c7d80'
CRUDE_OIL_ID = 'a4c8e2f0-1b3d-5e7f-8091-a2b3c4d5e6f7'
GOLD_OPTION_ID = 'c7e9a1b3-5d7f-5913-a5c7-e9f1a3b5c7d9'


class MarketContextAndQuantitiesExample:
    """Reads market context, converts quantities and reads extra broker attributes.

    Attributes:
        cache (FakeRedis): The in-memory Redis stand-in.
        placement (EnginePlacement): The placement being shown.
    """

    def __init__(self):
        """Sets the configuration, fills Redis and builds the placement.

        Returns:
            None: This method returns nothing.
        """
        api_configuration['order_broker_selector'] = 'fixed_priority'
        api_configuration['order_warm_brokers'] = []
        self.cache = FakeRedis()
        self.cache.strings['unified:catalogue:current_date'] = MAPPING_DATE
        self.cache.strings['unified:catalogue:warm_identifier'] = 'warm-0930-a'
        self.cache.hashes[PREFIX + 'identity'] = {}
        self.cache.hashes[PREFIX + 'order_handles'] = {}
        self.cache.hashes[PREFIX + 'contract_sizes'] = {}
        self.add_instrument(INFOSYS_ID, 'nse', 'nse_equities', 'security', 'INFY', 1.0, None)
        self.add_instrument(
            CRUDE_OIL_ID,
            'mcx',
            'mcx_commodity_futures',
            'future',
            'CRUDEOIL26OCTFUT',
            1.0,
            {
                'units_per_lot': '100',
                'status': 'confirmed',
                'tradeable': True,
            },
        )
        self.add_instrument(
            GOLD_OPTION_ID,
            'mcx',
            'mcx_commodity_options',
            'option',
            'GOLD26OCT120000CE',
            1.0,
            {
                'units_per_lot': None,
                'status': 'conflict',
                'tradeable': False,
            },
        )
        self.cache.hashes['unified:quotes:live'] = {
            CRUDE_OIL_ID: json.dumps({
                'instrument_id': CRUDE_OIL_ID,
                'broker': 'zerodha',
                'segment': 'mcx_commodity_futures',
                'last_price': 5987.0,
                'volume': 1843200,
            }),
        }
        self.cache.strings['unified:portfolio:positions'] = json.dumps({
            'net': [
                {
                    'instrument_id': CRUDE_OIL_ID,
                    'broker': 'zerodha',
                    'product': 'NRML',
                    'quantity': 300,
                },
            ],
        })
        self.cache.hashes[PREFIX + 'additional_attributes'] = {
            INFOSYS_ID: json.dumps({
                'zerodha': {
                    'freeze_quantity': None,
                },
                'dhan': {
                    'freeze_quantity': '100000',
                },
            }),
        }
        self.placement = EnginePlacement(self.cache, logging.getLogger('example'))

    def add_instrument(
        self,
        instrument_id,
        exchange,
        segment,
        shape,
        order_symbol,
        broker_lot_size,
        contract_size,
    ):
        """Writes one instrument's identity, Zerodha and Dhan order handles and contract size decision.

        Args:
            instrument_id (str): The instrument id.
            exchange (str): The canonical exchange.
            segment (str): The exchange-prefixed segment.
            shape (str): `security`, `future` or `option`.
            order_symbol (str): The trading symbol both brokers order it by.
            broker_lot_size (float): The lot size in each broker's own handle.
            contract_size (dict | None): This morning's contract size decision, or None for a security.

        Returns:
            None: This method returns nothing.
        """
        self.cache.hashes[PREFIX + 'identity'][instrument_id] = json.dumps({
            'instrument_id': instrument_id,
            'exchange': exchange,
            'segment': segment,
            'shape': shape,
            'mapping_date': MAPPING_DATE,
        })
        handles = {}
        for broker_name in (
            'zerodha',
            'dhan',
        ):
            handles[broker_name] = {
                'broker_token': f'{broker_name}-{order_symbol}',
                'order_symbol': order_symbol,
                'lot_size': broker_lot_size,
                'tick_size': 0.05,
            }
        self.cache.hashes[PREFIX + 'order_handles'][instrument_id] = json.dumps(handles)
        if contract_size is not None:
            self.cache.hashes[PREFIX + 'contract_sizes'][instrument_id] = json.dumps(contract_size)

    def run(self):
        """Reads the context twice, converts four quantities and reads two instruments' attributes.

        Returns:
            None: This method returns nothing.
        """
        before = self.cache.round_trips
        instrument, quote, positions = self.placement.market_context(CRUDE_OIL_ID, True, True)
        print(f'first read: {instrument.segment}, trusted units per lot {instrument.trusted_units_per_lot()}, round trips {self.cache.round_trips - before}')
        print(f'  quote last_price {quote["last_price"]}, positions {positions["net"]}')
        before = self.cache.round_trips
        instrument, quote, positions = self.placement.market_context(CRUDE_OIL_ID, True, False)
        print(f'second read, quote only: positions {positions}, round trips {self.cache.round_trips - before}')

        print(f'25 Infosys shares at zerodha: {self.placement.broker_quantity("zerodha", INFOSYS_ID, 25)}')
        print(f'300 barrels of crude oil at zerodha: {self.placement.broker_quantity("zerodha", CRUDE_OIL_ID, 300)} lots')
        for instrument_id, units in (
            (
                CRUDE_OIL_ID,
                250,
            ),
            (
                GOLD_OPTION_ID,
                100,
            ),
        ):
            try:
                self.placement.broker_quantity('zerodha', instrument_id, units)
            except RefusedRequestError as refusal:
                print(f'{units} units: {refusal.status} {refusal.body["error"]}')

        print(f'attributes of Infosys: {self.placement.broker_attributes(INFOSYS_ID)}')
        print(f'attributes of crude oil: {self.placement.broker_attributes(CRUDE_OIL_ID)}')


if __name__ == '__main__':
    MarketContextAndQuantitiesExample().run()
