"""Builds the three single reference orders from a tiny stand-in catalogue, skipping a NIFTY future that has already expired.

A `ReferenceOrders` reads today's catalogue and live quotes from Redis and builds the orders every broker's calculator is asked about: 1 INFY share bought intraday, 1 lot of the nearest NIFTY future sold, and 1 lot of the nearest crude oil future bought, each at its last traded price. A lot's size comes from the quote, or from today's contract size decision for a commodity. This program answers from a stand-in Redis holding a few instruments, so it needs nothing running.

It also calls the readers the three builders share: `catalogue_key`, `text`, `members`, `quote`, `instrument` and `leg_for`.

Notice that the NIFTY future expiring on 2026-09-29 is passed over for the October one, because the orders are built for 2026-09-30, and that crude oil's lot is 100 barrels from its contract size.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/utilities/reference_orders/ReferenceOrders/example_1_the_single_orders.py
"""

import datetime
import json

from unified_broker_interface.utilities.margin_calculators.utilities.reference_orders import (
    ReferenceOrders,
)


class StandInPipeline:
    """A pipeline that queues `HGET`s on a stand-in Redis and answers them together.

    Attributes:
        cache (StandInRedis): The stand-in Redis.
        queued (list): The queued `(name, key)` pairs.
    """

    def __init__(self, cache):
        """Builds the pipeline.

        Args:
            cache (StandInRedis): The stand-in Redis.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.queued = []

    def hget(self, name, key):
        """Queues an `HGET`.

        Args:
            name (str): The hash.
            key (str): The field.

        Returns:
            StandInPipeline: This pipeline.
        """
        self.queued.append((name, key))
        return self

    def execute(self):
        """Answers every queued `HGET`.

        Returns:
            list: The values, None where a field is missing.
        """
        replies = []
        for name, key in self.queued:
            replies.append(self.cache.hget(name, key))
        return replies


class StandInRedis:
    """A Redis holding a tiny catalogue for 2026-09-30: strings, hashes and sorted sets read by prefix.

    Attributes:
        strings (dict): String keys.
        hashes (dict): Hashes, each a dict.
        sorted_sets (dict): Sorted sets, each a list of members.
    """

    def __init__(self):
        """Builds an empty Redis with today's catalogue date.

        Returns:
            None: This method returns nothing.
        """
        self.strings = {
            'unified:catalogue:current_date': '2026-09-30',
        }
        self.hashes = {}
        self.sorted_sets = {}

    def add_instrument(self, segment, member, identity, handles, last_price, lot_size, contract_size=None):
        """Adds an instrument to the catalogue with a quote.

        Args:
            segment (str): The segment.
            member (str): The catalogue member, ending in the instrument id.
            identity (dict): The identity.
            handles (dict): The order handles.
            last_price (float): The last traded price.
            lot_size (int): The exchange lot size.
            contract_size (dict | None): The contract size decision, for a commodity.

        Returns:
            None: This method returns nothing.
        """
        instrument_id = member.split('|')[-1]
        prefix = 'unified:catalogue:2026-09-30:'
        self.sorted_sets.setdefault(f'{prefix}catalogue:{segment}', []).append(member)
        self.hashes.setdefault(f'{prefix}identity', {})[instrument_id] = json.dumps(identity)
        self.hashes.setdefault(f'{prefix}order_handles', {})[instrument_id] = json.dumps(handles)
        if contract_size is not None:
            self.hashes.setdefault(f'{prefix}contract_sizes', {})[instrument_id] = json.dumps(contract_size)
        quote = {
            'last_price': last_price,
            'lot_size': lot_size,
        }
        self.hashes.setdefault('unified:quotes:live', {})[instrument_id] = json.dumps(quote)

    def get(self, key):
        """Reads a string.

        Args:
            key (str): The key.

        Returns:
            str | None: The value.
        """
        return self.strings.get(key)

    def hget(self, name, key):
        """Reads a hash field.

        Args:
            name (str): The hash.
            key (str): The field.

        Returns:
            str | None: The value.
        """
        return self.hashes.get(name, {}).get(key)

    def zrangebylex(self, name, minimum, maximum):
        """The members of a sorted set between two bounds, both given as `[text`.

        Args:
            name (str): The sorted set.
            minimum (str): The lower bound.
            maximum (str): The upper bound.

        Returns:
            list: The members, in order.
        """
        found = []
        for member in sorted(self.sorted_sets.get(name, [])):
            if minimum[1:] <= member <= maximum[1:]:
                found.append(member)
        return found

    def pipeline(self, transaction=True):
        """A pipeline.

        Args:
            transaction (bool): Ignored.

        Returns:
            StandInPipeline: The pipeline.
        """
        del transaction
        return StandInPipeline(self)


class TheSingleOrdersExample:
    """Builds the three single reference orders.

    Attributes:
        orders (ReferenceOrders): The builder, over the stand-in Redis.
    """

    def __init__(self):
        """Fills the stand-in catalogue and builds the builder for 2026-09-30.

        Returns:
            None: This method returns nothing.
        """
        cache = StandInRedis()
        equity = {
            'segment': 'nse_equities',
            'shape': 'security',
        }
        future = {
            'segment': 'nse_equity_index_futures',
            'shape': 'future',
            'underlying_symbol': 'NIFTY',
        }
        crude = {
            'segment': 'mcx_commodity_futures',
            'shape': 'future',
            'underlying_symbol': 'CRUDEOIL',
        }
        handles = {
            'zerodha': {
                'order_symbol': 'stand-in',
            },
        }
        contract_size = {
            'units_per_lot': '100',
            'status': 'confirmed',
            'tradeable': True,
        }
        cache.add_instrument('nse_equities', 'INFY||||infy', equity, handles, 1017.7, 1)
        cache.add_instrument('nse_equity_index_futures', 'NIFTY|2026-09-29|||nifty-sep', future, handles, 22790.0, 65)
        cache.add_instrument('nse_equity_index_futures', 'NIFTY|2026-10-27|||nifty-oct', future, handles, 22833.7, 65)
        cache.add_instrument('mcx_commodity_futures', 'CRUDEOIL|2026-10-19|||crude-oct', crude, handles, 8618, 1, contract_size)
        self.orders = ReferenceOrders(cache, datetime.date(2026, 9, 30))

    def run(self):
        """Prints each reference order.

        Returns:
            None: This method returns nothing.
        """
        print(f'Catalogue date: {self.orders.mapping_date}')
        print(f'Identity key: {self.orders.catalogue_key("identity")}')
        print(f'Text of b"INFY": {self.orders.text(b"INFY")!r}')
        print(f'NIFTY futures in the catalogue: {self.orders.members("nse_equity_index_futures", "NIFTY|")}')
        print(f'INFY quote: {self.orders.quote("infy")}')
        print(f'INFY instrument segment: {self.orders.instrument("infy").segment}')
        manual = self.orders.leg_for('INFY bought for delivery', 'INFY||||infy', 'BUY', 'CNC', 10)
        print(f'leg_for 10 shares: {manual.units} units at {manual.price}')
        legs = [
            self.orders.intraday_leg(),
            self.orders.fno_leg(),
            self.orders.commodity_leg(),
        ]
        for leg in legs:
            print(f'{leg.name}: {leg.instrument.instrument_id}, {leg.transaction_type} {leg.units} units {leg.product} at {leg.price}')


if __name__ == '__main__':
    TheSingleOrdersExample().run()
