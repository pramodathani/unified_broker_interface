"""Runs a whole calibration against three stand-in brokers and a stand-in database, the way the daily script does.

`measure` builds the reference orders from Redis, asks every broker that has a login in Redis about each one it `takes`, and prices the condor as a basket and leg by leg where the broker has a basket calculator. `write` then updates `unified.broker_order_costs` with every measured figure, and leaves unmeasured ones as they are through `COALESCE`. This program uses a stand-in Redis holding a small catalogue and three logins, three stand-in calculators that answer from a table instead of calling a broker, and a stand-in database that prints what would be written. A fourth broker has no login, so `calculator` skips it with a warning. Before the whole run, the program takes the first steps by hand: `calculator`, `reference_legs` and `measure_broker` for one broker.

Notice that `gamma` charges 10% more than the other two and has no basket calculator, so its hedge result is None and is written as None, which keeps the table's own value.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/utilities/margin_calibration/MarginCalibration/example_2_a_whole_run_against_stand_ins.py
"""

import decimal
import json

from unified_broker_interface.utilities.broker_orders.zerodha import ZerodhaOrders
from unified_broker_interface.utilities.margin_calculators.base import (
    BrokerMarginCalculator,
)
from unified_broker_interface.utilities.margin_calculators.utilities.margin_calibration import (
    MarginCalibration,
)
from unified_broker_interface.utilities.margin_calculators.utilities.reference_orders import (
    ReferenceOrders,
)
from utilities import configurations

EXCHANGE_ANSWERS = {
    'INFY bought intraday': '203.48',
    'NIFTY future sold': '167109.41',
    'crude oil future bought': '271072.50',
    'NIFTY 23200 CE bought call': '1235.00',
    'NIFTY 22400 PE bought put': '2476.50',
    'NIFTY 23000 CE sold call': '150000.00',
    'NIFTY 22600 PE sold put': '150000.00',
}


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


class PrintingLogger:
    """A logger that prints warnings on one line."""

    def warning(self, message):
        """Prints a warning.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'WARNING {message}')


class TableCalculator(BrokerMarginCalculator):
    """A calculator that answers from a table instead of calling a broker, reusing Zerodha's markets and quantity rules.

    Attributes:
        SURCHARGE (decimal.Decimal): How much more than the exchange this broker charges.
    """

    ORDER_CLASS = ZerodhaOrders
    TAKES_BASKETS = True
    SURCHARGE = decimal.Decimal(1)

    def order_margin(self, leg):
        """The exchange's answer for the leg, times the surcharge.

        Args:
            leg (ReferenceLeg): The order.

        Returns:
            decimal.Decimal: The margin.
        """
        return decimal.Decimal(EXCHANGE_ANSWERS[leg.name]) * self.SURCHARGE

    def basket_margin(self, legs):
        """A hedged condor's margin, or None without a basket calculator.

        Args:
            legs (list): The legs.

        Returns:
            decimal.Decimal | None: The margin.
        """
        if not self.TAKES_BASKETS:
            return None
        return decimal.Decimal('75614.55') * self.SURCHARGE


class AlphaCalculator(TableCalculator):
    """A broker that charges the exchange's margin."""

    BROKER_NAME = 'alpha'


class BetaCalculator(TableCalculator):
    """Another broker that charges the exchange's margin."""

    BROKER_NAME = 'beta'


class GammaCalculator(TableCalculator):
    """A broker that charges 10% more and has no basket calculator."""

    BROKER_NAME = 'gamma'
    TAKES_BASKETS = False
    SURCHARGE = decimal.Decimal('1.1')


class DeltaCalculator(TableCalculator):
    """A broker with no login in Redis."""

    BROKER_NAME = 'delta'


class PrintingCursor:
    """A cursor that prints each update instead of running it.

    Attributes:
        rowcount (int): One row per update.
    """

    def __init__(self):
        """Builds the cursor.

        Returns:
            None: This method returns nothing.
        """
        self.rowcount = 1

    def __enter__(self):
        """Enters the `with` block.

        Returns:
            PrintingCursor: This cursor.
        """
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Leaves the `with` block.

        Args:
            exception_type (type | None): The exception's type.
            exception (BaseException | None): The exception.
            traceback (types.TracebackType | None): The traceback.

        Returns:
            bool: False.
        """
        del exception_type
        del exception
        del traceback
        return False

    def execute(self, query, parameters):
        """Prints the update's parameters.

        Args:
            query (str): The SQL.
            parameters (tuple): The intraday, F&O and commodity multipliers, the hedge result and the broker.

        Returns:
            None: This method returns nothing.
        """
        del query
        print(f'UPDATE {parameters[4]}: intraday {parameters[0]}, fno {parameters[1]}, commodity {parameters[2]}, hedge {parameters[3]}')


class PrintingConnection:
    """A connection whose cursor prints updates."""

    def cursor(self):
        """A printing cursor.

        Returns:
            PrintingCursor: The cursor.
        """
        return PrintingCursor()

    def commit(self):
        """Prints the commit.

        Returns:
            None: This method returns nothing.
        """
        print('COMMIT')

    def close(self):
        """Closes nothing.

        Returns:
            None: This method returns nothing.
        """


class AWholeRunAgainstStandInsExample:
    """Measures three stand-in brokers and writes their figures.

    Attributes:
        calibration (MarginCalibration): The calibration.
    """

    def __init__(self):
        """Fills the stand-in Redis and points the database at the printing stand-in.

        Returns:
            None: This method returns nothing.
        """
        cache = StandInRedis()
        handles = {}
        for broker_name in ['alpha', 'beta', 'gamma', 'delta']:
            handles[broker_name] = {
                'order_symbol': 'stand-in',
                'lot_size': '1.0',
            }
            if broker_name != 'delta':
                cache.hashes.setdefault('last_login', {})[broker_name] = json.dumps({'access_token': 'stand-in-token'})
                cache.hashes.setdefault('settings', {})[broker_name] = json.dumps({'api_key': 'stand-in-key'})
        equity = {
            'segment': 'nse_equities',
            'shape': 'security',
        }
        future = {
            'segment': 'nse_equity_index_futures',
            'shape': 'future',
        }
        crude = {
            'segment': 'mcx_commodity_futures',
            'shape': 'future',
        }
        contract_size = {
            'units_per_lot': '100',
            'status': 'confirmed',
            'tradeable': True,
        }
        cache.add_instrument('nse_equities', 'INFY||||infy', equity, handles, 1017.7, 1)
        cache.add_instrument('nse_equity_index_futures', 'NIFTY|2026-10-27|||nifty-oct', future, handles, 22833.7, 65)
        cache.add_instrument('mcx_commodity_futures', 'CRUDEOIL|2026-10-19|||crude-oct', crude, handles, 8618, 1, contract_size)
        options = {
            ('22400', 'PE'): 38.1,
            ('22600', 'PE'): 82.0,
            ('23000', 'CE'): 51.6,
            ('23200', 'CE'): 19.0,
        }
        for (strike, option_type), premium in options.items():
            option = {
                'segment': 'nse_equity_index_options',
                'shape': 'option',
            }
            member = f'NIFTY|2026-10-06|{decimal.Decimal(strike):016.4f}|{option_type}|{strike}-{option_type}'
            cache.add_instrument('nse_equity_index_options', member, option, handles, premium, 65)
        configurations.get_postgres = PrintingConnection
        calculator_classes = [
            AlphaCalculator,
            BetaCalculator,
            GammaCalculator,
            DeltaCalculator,
        ]
        self.calibration = MarginCalibration(cache, PrintingLogger(), calculator_classes)

    def run(self):
        """Measures, prints the exchange's margins, and writes.

        Returns:
            None: This method returns nothing.
        """
        missing = self.calibration.calculator(DeltaCalculator)
        print(f'A calculator for delta: {missing}')
        reference_orders = ReferenceOrders(self.calibration.cache)
        legs, condor = self.calibration.reference_legs(reference_orders)
        print(f'Reference orders: {sorted(legs)}, condor legs: {len(condor)}')
        alpha = self.calibration.measure_broker(self.calibration.calculator(AlphaCalculator), legs, condor)
        print(f'alpha alone: {alpha.margins}, basket {alpha.basket_margin}, legs {alpha.legs_margin}')
        measurements = self.calibration.measure()
        exchange = self.calibration.exchange_margins(measurements)
        print(f'Exchange margins: {exchange}')
        updated = self.calibration.write(measurements, exchange)
        print(f'Rows updated: {updated}')


if __name__ == '__main__':
    AWholeRunAgainstStandInsExample().run()
