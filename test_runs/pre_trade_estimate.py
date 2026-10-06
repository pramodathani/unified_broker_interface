"""Offline checks of the pre-trade cost estimate: the book walk, the daily volatility and volume, the square-root model's coefficients, the estimate itself, and the check against measured orders.

The expected figures were worked out by hand and with Python's `math` and `statistics` modules outside the code under test, on a NIFTY option book near 238 rupees. A stand-in database answers the estimate check's queries, so no PostgreSQL, Redis, credentials or network are used.

Typical usage:

    python -m test_runs.pre_trade_estimate
"""

import datetime
import decimal
import logging
import sys

from test_runs.execution_cost_stand_ins import StandInExecutionDatabase
from unified_broker_interface.utilities.execution_costs.book_walk import (
    BookWalk,
)
from unified_broker_interface.utilities.execution_costs.daily_liquidity import (
    DailyLiquidity,
)
from unified_broker_interface.utilities.execution_costs.estimate_check import (
    EstimateCheck,
)
from unified_broker_interface.utilities.execution_costs.impact_coefficients import (
    ImpactCoefficients,
)
from unified_broker_interface.utilities.execution_costs.pre_trade_estimate import (
    PreTradeEstimate,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
OPTION = 'option-nifty-23800-ce'
BIDS = [
    ('238.00', 300),
    ('237.90', 450),
    ('237.75', 600),
    ('237.50', 1000),
    ('237.25', 800),
]
ASKS = [
    ('238.50', 300),
    ('238.60', 450),
    ('238.75', 600),
    ('239.00', 1000),
    ('239.25', 800),
]


class PreTradeEstimateSuite:
    """Runs every check and reports how many passed.

    Attributes:
        logger (logging.Logger): A logger that writes nothing.
        passed (int): How many checks passed.
        failed (list): The names of the checks that failed.
    """

    def __init__(self):
        """Builds the suite.

        Returns:
            None: This method returns nothing.
        """
        self.logger = logging.getLogger('test_runs.pre_trade_estimate')
        self.logger.addHandler(logging.NullHandler())
        self.logger.propagate = False
        self.passed = 0
        self.failed = []

    def check(self, name, actual, expected):
        """Compares one value with what it should be, and prints the difference when they differ.

        Args:
            name (str): What is being checked.
            actual (object): The value produced.
            expected (object): The value it should be.

        Returns:
            None: This method returns nothing.
        """
        if actual == expected:
            self.passed = self.passed + 1
            return
        self.failed.append(name)
        print(f'FAILED  {name}')
        print(f'  expected: {expected!r}')
        print(f'  actual:   {actual!r}')

    def levels(self, side):
        """A side of the scripted book with decimal prices.

        Args:
            side (list): Tuples of price (str) and quantity (int).

        Returns:
            list: Tuples of price (decimal.Decimal) and quantity (int).
        """
        levels = []
        for price, quantity in side:
            levels.append((decimal.Decimal(price), quantity))
        return levels

    def alternating_liquidity(self):
        """Twenty-one closes alternating between 100 and 110, and twenty days of a million units.

        Returns:
            DailyLiquidity: The figures; the returns are ±ln(1.1), whose sample standard deviation is 0.0977862 to seven places.
        """
        closes = []
        for index in range(21):
            if index % 2 == 0:
                closes.append(decimal.Decimal(100))
            else:
                closes.append(decimal.Decimal(110))
        volumes = []
        for index in range(20):
            volumes.append(1000000)
        return DailyLiquidity(closes, volumes)

    def run(self):
        """Runs every check and prints how many passed.

        Returns:
            int: 0 when every check passed, 1 when any failed.
        """
        self.a_walk_inside_the_best_level()
        self.a_walk_across_three_levels()
        self.a_walk_beyond_the_visible_book()
        self.empty_levels_are_left_out()
        self.volatility_of_alternating_closes()
        self.too_few_days_give_no_figures()
        self.only_the_last_twenty_days_count()
        self.coefficients_by_asset_class()
        self.an_estimate_the_book_covers()
        self.an_estimate_that_needs_the_model()
        self.an_estimate_without_the_model_inputs()
        self.a_sell_walks_the_bids()
        self.an_empty_side_cannot_be_priced()
        self.the_check_compares_crossing_and_resting_legs()
        self.the_check_reads_each_instruments_bars_once_a_day()

        total = self.passed + len(self.failed)
        print(f'{total - len(self.failed)}/{total} checks passed.')
        if self.failed:
            return 1
        return 0

    def a_walk_inside_the_best_level(self):
        """A buy of 100 against 300 at the best ask fills there alone.

        Returns:
            None: This method returns nothing.
        """
        walk = BookWalk(100, self.levels(ASKS))
        self.check('inside: filled and left', (walk.filled_quantity(), walk.remaining_quantity()), (100, 0))
        self.check('inside: average and worst', (walk.average_price(), walk.worst_price()), (decimal.Decimal('238.50'), decimal.Decimal('238.50')))
        self.check('inside: levels used', walk.levels_used(), 1)

    def a_walk_across_three_levels(self):
        """A buy of 1,200 takes 300 at 238.50, 450 at 238.60 and 450 at 238.75, an average of 238.63125.

        Returns:
            None: This method returns nothing.
        """
        walk = BookWalk(1200, self.levels(ASKS))
        self.check('three levels: average', walk.average_price(), decimal.Decimal('238.63125'))
        self.check('three levels: worst', walk.worst_price(), decimal.Decimal('238.75'))
        self.check('three levels: used', walk.levels_used(), 3)

    def a_walk_beyond_the_visible_book(self):
        """A buy of 5,000 empties the 3,150 visible units and leaves 1,850 beyond the last level at 239.25.

        Returns:
            None: This method returns nothing.
        """
        walk = BookWalk(5000, self.levels(ASKS))
        self.check('beyond: visible', walk.visible_quantity(), 3150)
        self.check('beyond: left', walk.remaining_quantity(), 1850)
        self.check('beyond: worst', walk.worst_price(), decimal.Decimal('239.25'))
        self.check('beyond: levels used', walk.levels_used(), 5)

    def empty_levels_are_left_out(self):
        """Levels with no price or no quantity are dropped, and nothing visible gives no price.

        Returns:
            None: This method returns nothing.
        """
        walk = BookWalk(10, [
            (None, 100),
            (decimal.Decimal('5'), 0),
            (decimal.Decimal('6'), 4),
        ])
        self.check('dropped levels', walk.levels, [(decimal.Decimal('6'), 4)])
        empty = BookWalk(10, [])
        self.check('nothing visible', (empty.average_price(), empty.worst_price(), empty.remaining_quantity()), (None, None, 10))

    def volatility_of_alternating_closes(self):
        """Closes alternating between 100 and 110 give a volatility of 0.0977862 and an average volume of a million.

        Returns:
            None: This method returns nothing.
        """
        liquidity = self.alternating_liquidity()
        self.check('volatility', liquidity.volatility().quantize(decimal.Decimal('0.0000001')), decimal.Decimal('0.0977862'))
        self.check('average volume', liquidity.average_volume(), decimal.Decimal(1000000))
        flat = DailyLiquidity([decimal.Decimal(100)] * 15, [10] * 15)
        self.check('flat price', flat.volatility(), decimal.Decimal(0))

    def too_few_days_give_no_figures(self):
        """Nine returns or nine volumes are too few, and a close of zero spoils the volatility.

        Returns:
            None: This method returns nothing.
        """
        short = DailyLiquidity([decimal.Decimal(100)] * 10, [10] * 9)
        self.check('nine returns', short.volatility(), None)
        self.check('nine volumes', short.average_volume(), None)
        broken = DailyLiquidity([decimal.Decimal(100)] * 10 + [decimal.Decimal(0)] + [decimal.Decimal(100)] * 10, [10] * 20)
        self.check('zero close', broken.volatility(), None)

    def only_the_last_twenty_days_count(self):
        """Older bars than the last twenty days, here a volume of ten million, are ignored.

        Returns:
            None: This method returns nothing.
        """
        liquidity = DailyLiquidity([decimal.Decimal(100)] * 30, [10000000] * 10 + [1000] * 20)
        self.check('closes kept', len(liquidity.closes), 21)
        self.check('volume of the last twenty', liquidity.average_volume(), decimal.Decimal(1000))

    def coefficients_by_asset_class(self):
        """Segments map to asset classes, and only a row with `fitted_at` counts as fitted.

        Returns:
            None: This method returns nothing.
        """
        fitted_at = datetime.datetime(2026, 10, 6, tzinfo=INDIA)
        coefficients = ImpactCoefficients({
            'securities': (decimal.Decimal('1.0'), None),
            'commodity': (decimal.Decimal('0.7'), fitted_at),
        })
        self.check('option is securities', coefficients.asset_class('nse_equity_index_options'), 'securities')
        self.check('crude is commodity', coefficients.asset_class('mcx_commodity_futures'), 'commodity')
        self.check('unknown segment', coefficients.asset_class('nse_nothing'), None)
        self.check('securities coefficient', coefficients.coefficient('nse_equities'), decimal.Decimal('1.0'))
        self.check('currency has no row', coefficients.coefficient('nse_currency_futures'), None)
        self.check('fitted flags', (coefficients.is_fitted('nse_equities'), coefficients.is_fitted('mcx_commodity_futures')), (False, True))
        database = StandInExecutionDatabase()
        database.coefficient_rows = [
            ('securities', decimal.Decimal('1.0'), None),
        ]
        loaded = ImpactCoefficients()
        with database.connect().cursor() as cursor:
            self.check('rows loaded', loaded.load(cursor), 1)
        self.check('loaded coefficient', loaded.coefficient('nse_equities'), decimal.Decimal('1.0'))

    def an_estimate_the_book_covers(self):
        """A buy of 1,200 costs 0.25 of half spread and 0.13125 of book walk, 16.00 basis points, with no model needed.

        Returns:
            None: This method returns nothing.
        """
        estimate = PreTradeEstimate('BUY', 1200, self.levels(BIDS), self.levels(ASKS))
        self.check('covered: parts', (estimate.half_spread(), estimate.book_walk(), estimate.beyond_book()), (decimal.Decimal('0.2500'), decimal.Decimal('0.1312'), decimal.Decimal('0')))
        self.check('covered: total', estimate.total(), decimal.Decimal('0.3812'))
        self.check('covered: basis points', estimate.basis_points(), decimal.Decimal('16.00'))
        self.check('covered: average price', estimate.average_price(), decimal.Decimal('238.6312'))
        self.check('covered: rupees', estimate.rupees(), decimal.Decimal('457.44'))
        self.check('covered: flag', estimate.is_covered_by_book(), True)

    def an_estimate_that_needs_the_model(self):
        """A buy of 5,000 leaves 1,850 beyond the book, which the model prices at 1.0021 a unit, adding 0.3708 to the whole order.

        Returns:
            None: This method returns nothing.
        """
        estimate = PreTradeEstimate('BUY', 5000, self.levels(BIDS), self.levels(ASKS), self.alternating_liquidity(), decimal.Decimal('1.0'))
        self.check('model: book walk', estimate.book_walk(), decimal.Decimal('0.5365'))
        self.check('model: remainder impact', estimate.remainder_impact(), decimal.Decimal('1.0021'))
        self.check('model: beyond book', estimate.beyond_book(), decimal.Decimal('0.3708'))
        self.check('model: total', estimate.total(), decimal.Decimal('1.1573'))
        self.check('model: basis points', estimate.basis_points(), decimal.Decimal('48.58'))
        self.check('model: average price', estimate.average_price(), decimal.Decimal('239.4073'))
        self.check('model: flag', estimate.is_covered_by_book(), False)

    def an_estimate_without_the_model_inputs(self):
        """The same order with no volatility, or no coefficient, has no beyond-book part and so no total.

        Returns:
            None: This method returns nothing.
        """
        without_liquidity = PreTradeEstimate('BUY', 5000, self.levels(BIDS), self.levels(ASKS), None, decimal.Decimal('1.0'))
        self.check('no liquidity: total', without_liquidity.total(), None)
        self.check('no liquidity: book parts kept', without_liquidity.book_walk(), decimal.Decimal('0.5365'))
        without_coefficient = PreTradeEstimate('BUY', 5000, self.levels(BIDS), self.levels(ASKS), self.alternating_liquidity(), None)
        self.check('no coefficient: total', without_coefficient.total(), None)

    def a_sell_walks_the_bids(self):
        """A sell of 400 takes 300 at 238.00 and 100 at 237.90, costing 0.25 and 0.025 below the mid-price.

        Returns:
            None: This method returns nothing.
        """
        estimate = PreTradeEstimate('SELL', 400, self.levels(BIDS), self.levels(ASKS))
        self.check('sell: touch', estimate.touch(), decimal.Decimal('238.00'))
        self.check('sell: parts', (estimate.half_spread(), estimate.book_walk()), (decimal.Decimal('0.2500'), decimal.Decimal('0.0250')))
        self.check('sell: average price', estimate.average_price(), decimal.Decimal('237.9750'))
        small = PreTradeEstimate('SELL', 100, self.levels(BIDS), self.levels(ASKS))
        self.check('sell: no walk is plain zero', str(small.book_walk()), '0.0000')

    def an_empty_side_cannot_be_priced(self):
        """With no asks there is no mid-price, so nothing can be estimated.

        Returns:
            None: This method returns nothing.
        """
        estimate = PreTradeEstimate('BUY', 100, self.levels(BIDS), [])
        self.check('empty: priceable', estimate.is_priceable(), False)
        self.check('empty: figures', (estimate.mid(), estimate.half_spread(), estimate.total(), estimate.basis_points()), (None, None, None, None))

    def check_database(self):
        """A stand-in database with three measured legs: a market buy, a stop sell and a buy with no book.

        Returns:
            StandInExecutionDatabase: The database.
        """
        database = StandInExecutionDatabase()
        database.coefficient_rows = [
            ('securities', decimal.Decimal('1.0'), None),
        ]
        decided_at = datetime.datetime(2026, 10, 6, 10, 15, 0, tzinfo=INDIA)
        database.add_book(OPTION, decided_at - datetime.timedelta(seconds=1), BIDS, ASKS)
        for day in range(25):
            bar_time = datetime.datetime(2026, 9, 1, tzinfo=INDIA) + datetime.timedelta(days=day)
            close = decimal.Decimal(100)
            if day % 2 == 1:
                close = decimal.Decimal(110)
            database.daily_bars.setdefault(OPTION, []).append((bar_time, close, 1000000))
        database.estimate_legs = [
            ('market', '1', 'zerodha', OPTION, 'nse_equity_index_options', 'BUY', 'MARKET', None, 1200, decided_at, decimal.Decimal('238.25'), decimal.Decimal('0.25'), decimal.Decimal('0.15')),
            ('stop', '1', 'zerodha', OPTION, 'nse_equity_index_options', 'SELL', 'SL', decimal.Decimal('238.10'), 65, decided_at, decimal.Decimal('238.25'), decimal.Decimal('0.25'), decimal.Decimal('-3.00')),
            ('no book', '1', 'zerodha', 'option-without-ticks', 'nse_equity_index_options', 'BUY', 'LIMIT', decimal.Decimal('50'), 65, decided_at, decimal.Decimal('50'), decimal.Decimal('0.05'), decimal.Decimal('0')),
        ]
        return database

    def the_check_compares_crossing_and_resting_legs(self):
        """The market buy is crossing, estimated at 16.00 and measured at 16.79; the stop is resting whatever its price; the limit with no book has no estimate and counts as resting, because it cannot be shown to cross.

        Returns:
            None: This method returns nothing.
        """
        database = self.check_database()
        check = EstimateCheck(database.connect, self.logger)
        start = datetime.datetime(2026, 10, 6, tzinfo=INDIA)
        comparisons = check.compare(start, start + datetime.timedelta(days=1))
        market = comparisons[0]
        self.check('market: crossing', market['crossing'], True)
        self.check('market: figures', (market['estimated_basis_points'], market['actual_basis_points']), (decimal.Decimal('16.00'), decimal.Decimal('16.79')))
        self.check('market: covered', market['covered_by_book'], True)
        self.check('stop: resting', comparisons[1]['crossing'], False)
        self.check('no book: no estimate', (comparisons[2]['estimated_basis_points'], comparisons[2]['covered_by_book']), (None, None))
        summary = check.summary(comparisons)
        self.check('summary: crossing', (summary[0]['legs'], summary[0]['estimated'], summary[0]['mean_absolute_difference']), (1, 1, decimal.Decimal('0.79')))
        self.check('summary: resting', (summary[1]['kind'], summary[1]['legs'], summary[1]['estimated']), ('resting', 2, 1))
        self.check('coefficients read', check.coefficients.coefficient('nse_equities'), decimal.Decimal('1.0'))

    def the_check_reads_each_instruments_bars_once_a_day(self):
        """Two legs on the same instrument and day read the daily bars once.

        Returns:
            None: This method returns nothing.
        """
        database = self.check_database()
        check = EstimateCheck(database.connect, self.logger)
        start = datetime.datetime(2026, 10, 6, tzinfo=INDIA)
        check.compare(start, start + datetime.timedelta(days=1))
        self.check('bars read once', database.daily_bar_reads, 1)
        liquidity = check.liquidity_cache[(OPTION, datetime.date(2026, 10, 6))]
        self.check('bars before the day', len(liquidity.closes), 21)


if __name__ == '__main__':
    sys.exit(PreTradeEstimateSuite().run())
