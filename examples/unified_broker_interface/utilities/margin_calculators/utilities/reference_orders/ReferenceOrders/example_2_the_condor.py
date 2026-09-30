"""Builds the NIFTY iron condor around the index's level, and shows that a missing option means no condor.

`condor_legs` rounds the index level to the nearest 100, then takes the nearest weekly expiry after today, buys the call 400 points above and the put 400 below, and sells the call 200 above and the put 200 below, one lot each, bought legs first. An expiry that is today is skipped, because an option on its last day can be priced oddly. When any of the four options, or its quote, is missing, it answers None, and the calibration skips the hedge test rather than test a lopsided position. This program answers from a stand-in Redis.

Notice that the options expiring on 2026-09-30 itself are not used, and that removing one option's quote gives None.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/utilities/reference_orders/ReferenceOrders/example_2_the_condor.py
"""

import datetime
import decimal
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


class TheCondorExample:
    """Builds the condor from a stand-in catalogue of NIFTY options.

    Attributes:
        cache (StandInRedis): The stand-in Redis.
        orders (ReferenceOrders): The builder.
    """

    def __init__(self):
        """Fills the catalogue with options on two expiries.

        Returns:
            None: This method returns nothing.
        """
        self.cache = StandInRedis()
        premiums = {
            ('22400', 'PE'): 38.1,
            ('22600', 'PE'): 82.0,
            ('23000', 'CE'): 51.6,
            ('23200', 'CE'): 19.0,
        }
        handles = {
            'zerodha': {
                'order_symbol': 'stand-in',
            },
        }
        for expiry in ['2026-09-30', '2026-10-06']:
            for (strike, option_type), premium in premiums.items():
                identity = {
                    'segment': 'nse_equity_index_options',
                    'shape': 'option',
                    'underlying_symbol': 'NIFTY',
                    'expiry_date': expiry,
                    'strike_price': strike,
                    'option_type': option_type,
                }
                member = f'NIFTY|{expiry}|{decimal.Decimal(strike):016.4f}|{option_type}|{expiry}-{strike}-{option_type}'
                self.cache.add_instrument('nse_equity_index_options', member, identity, handles, premium, 65)
        self.orders = ReferenceOrders(self.cache, datetime.date(2026, 9, 30))

    def run(self):
        """Prints the condor around 22,833.70, then tries again without one option's quote.

        Returns:
            None: This method returns nothing.
        """
        member = self.orders.nearest_expiry_member('nse_equity_index_options', 'NIFTY|', datetime.date(2026, 10, 1))
        print(f'Nearest expiry after today: {member.split("|")[1]}')
        for leg in self.orders.condor_legs(decimal.Decimal('22833.7')):
            print(f'{leg.name}: {leg.instrument.instrument_id}, {leg.units} units at {leg.price}')
        del self.cache.hashes['unified:quotes:live']['2026-10-06-23200-CE']
        print(f'Without the 23200 call quote: {self.orders.condor_legs(decimal.Decimal("22833.7"))}')


if __name__ == '__main__':
    TheCondorExample().run()
