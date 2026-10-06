"""Offline checks of the execution cost measurement and the latency calibration: how a fill's cost is split, which legs are measured, what each broker's latency figures come to, and what is written.

The figures are worked out by hand from scripted quotes on a NIFTY option near 238 rupees, so a change to the arithmetic, to the choice of quote, or to which legs count fails here. A stand-in database answers the queries, so no PostgreSQL, Redis, credentials or network are used.

Typical usage:

    python -m test_runs.execution_costs
"""

import datetime
import decimal
import logging
import sys

from test_runs.execution_cost_stand_ins import StandInExecutionDatabase
from unified_broker_interface.utilities.execution_costs.execution_cost import (
    ExecutionCost,
)
from unified_broker_interface.utilities.execution_costs.execution_cost_measurement import (
    COST_COLUMNS,
    ExecutionCostMeasurement,
)
from unified_broker_interface.utilities.execution_costs.latency_calibration import (
    LatencyCalibration,
)
from unified_broker_interface.utilities.execution_costs.leg_execution import (
    LegExecution,
)
from unified_broker_interface.utilities.execution_costs.quote_moment import (
    QuoteMoment,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
DAY = datetime.date(2026, 10, 6)
OPTION = 'option-nifty-23800-ce'
STALE = 'option-without-recent-ticks'
CRUDE = 'future-crude-oil'


class ExecutionCostsSuite:
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
        self.logger = logging.getLogger('test_runs.execution_costs')
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

    def moment(self, hour, minute, second, millisecond=0, day=DAY):
        """A moment on a day in India's time zone.

        Args:
            hour (int): The hour.
            minute (int): The minute.
            second (int): The second.
            millisecond (int): The millisecond.
            day (datetime.date): The day.

        Returns:
            datetime.datetime: The moment.
        """
        return datetime.datetime(
            day.year,
            day.month,
            day.day,
            hour,
            minute,
            second,
            millisecond * 1000,
            INDIA,
        )

    def database(self):
        """A database holding the scripted day: a buy that walked the book and its stop, a sell, a stale quote, a rejection, a commodity fill and a leg from the day before.

        Returns:
            StandInExecutionDatabase: The database.
        """
        database = StandInExecutionDatabase()
        database.segments[OPTION] = 'nse_equity_index_options'
        database.segments[STALE] = 'nse_equity_options'
        database.segments[CRUDE] = 'mcx_commodity_futures'
        database.add_tick(OPTION, self.moment(10, 14, 59, 900), '238.00', '238.50')
        database.add_tick(OPTION, self.moment(10, 15, 0, 150), '238.10', '238.60')
        database.add_tick(OPTION, self.moment(10, 15, 0, 250), '238.20', '238.70')
        database.add_tick(OPTION, self.moment(10, 15, 0, 270), None, '238.70')
        database.add_tick(OPTION, self.moment(10, 19, 59, 950), '240.00', '240.40')
        database.add_tick(OPTION, self.moment(14, 59, 59, 0, datetime.date(2026, 10, 5)), '250.00', '250.20')
        database.add_tick(STALE, self.moment(10, 13, 0), '41.00', '41.20')
        database.add_tick(CRUDE, self.moment(21, 0, 0), '5210', '5211')
        self.add_leg(database, 'buy', 'entry', OPTION, 'BUY', (10, 15, 0, 0), (10, 15, 0, 200), (10, 15, 0, 300))
        database.add_event(self.moment(10, 15, 0, 400), 'buy', 'leg_update', leg_id='1', filled_quantity=30, average_price='238.80')
        database.add_event(self.moment(10, 15, 0, 450), 'buy', 'leg_update', leg_id='1', filled_quantity=65)
        database.add_event(self.moment(10, 15, 0, 460), 'buy', 'leg_update', leg_id='1', average_price='238.90')
        self.add_leg(database, 'buy', 'stop', OPTION, 'SELL', None, (10, 20, 0, 0), (10, 20, 0, 80), leg_id='2')
        database.add_event(self.moment(10, 20, 1), 'buy', 'leg_update', leg_id='2', filled_quantity=65, average_price='239.90')
        self.add_leg(database, 'sell', 'entry', OPTION, 'SELL', (10, 15, 0, 0), (10, 15, 0, 200), (10, 15, 0, 300))
        database.add_event(self.moment(10, 15, 0, 400), 'sell', 'leg_update', leg_id='1', filled_quantity=65, average_price='238.05')
        self.add_leg(database, 'stale', 'entry', STALE, 'BUY', (10, 15, 0, 0), (10, 15, 0, 200), (10, 15, 0, 300))
        database.add_event(self.moment(10, 15, 0, 400), 'stale', 'leg_update', leg_id='1', filled_quantity=50, average_price='41.25')
        self.add_leg(database, 'rejected', 'entry', OPTION, 'BUY', (10, 15, 0, 0), (10, 15, 0, 200), (10, 15, 0, 300), outcome='rejected')
        self.add_leg(database, 'crude', 'entry', CRUDE, 'BUY', (21, 0, 0, 100), (21, 0, 0, 200), (21, 0, 0, 300), broker='zerodha')
        database.add_event(self.moment(21, 0, 1), 'crude', 'leg_update', leg_id='1', filled_quantity=1, average_price='5212')
        yesterday = datetime.date(2026, 10, 5)
        database.add_event(self.moment(14, 59, 59, 900, yesterday), 'yesterday', 'parent_received', synthetic_type='simple')
        database.add_event(self.moment(15, 0, 0, 0, yesterday), 'yesterday', 'leg_requested', leg_id='1', leg_role='entry', broker='flattrade', instrument_id=OPTION, transaction_type='BUY', quantity=65)
        database.add_event(self.moment(15, 0, 0, 100, yesterday), 'yesterday', 'leg_answered', leg_id='1', outcome='accepted')
        database.add_event(self.moment(15, 0, 1, 0, yesterday), 'yesterday', 'leg_update', leg_id='1', filled_quantity=65, average_price='250.20')
        return database

    def add_leg(
        self,
        database,
        parent_order_id,
        role,
        instrument_id,
        transaction_type,
        received,
        requested,
        answered,
        leg_id='1',
        outcome='accepted',
        broker='flattrade',
    ):
        """Adds a parent's arrival, when it is given, and one leg's request and answer.

        Args:
            database (StandInExecutionDatabase): The database.
            parent_order_id (str): The parent.
            role (str): The leg's role.
            instrument_id (str): The instrument.
            transaction_type (str): `BUY` or `SELL`.
            received (tuple | None): The parent's arrival as (hour, minute, second, millisecond), or None for a later leg.
            requested (tuple): The leg's request time, in the same form.
            answered (tuple): The broker's answer time, in the same form.
            leg_id (str): The leg's id.
            outcome (str): The answer's outcome.
            broker (str): The broker.

        Returns:
            None: This method returns nothing.
        """
        if received is not None:
            database.add_event(self.moment(*received), parent_order_id, 'parent_received', synthetic_type='simple', instrument_id=instrument_id)
        database.add_event(self.moment(*requested), parent_order_id, 'leg_requested', synthetic_type='simple', leg_id=leg_id, leg_role=role, broker=broker, instrument_id=instrument_id, transaction_type=transaction_type, product='MIS', order_type='LIMIT', quantity=65)
        database.add_event(self.moment(*answered), parent_order_id, 'leg_answered', leg_id=leg_id, outcome=outcome)

    def measured(self, database, day_count=1):
        """Measures the scripted day, or more days ending with it.

        Args:
            database (StandInExecutionDatabase): The database.
            day_count (int): How many days.

        Returns:
            tuple: The measurement (ExecutionCostMeasurement) and the costs (list), keyed by parent and leg in a dict.
        """
        measurement = ExecutionCostMeasurement(database.connect, self.logger)
        start, end = measurement.day_bounds(DAY, day_count)
        costs = {}
        for cost in measurement.measure(start, end):
            costs[(cost.leg.parent_order_id, cost.leg.leg_id)] = cost
        return measurement, costs

    def run(self):
        """Runs every check and prints how many passed.

        Returns:
            int: 0 when every check passed, 1 when any failed.
        """
        self.a_buy_that_walked_the_book()
        self.a_sell_turns_every_sign()
        self.a_resting_order_filled_inside_the_spread()
        self.a_later_leg_is_measured_from_its_own_request()
        self.a_fill_is_read_across_several_updates()
        self.an_old_quote_counts_as_missing()
        self.a_one_sided_book_is_not_a_quote()
        self.unfilled_legs_and_other_days_are_left_out()
        self.a_commodity_fill_has_no_rupee_total()
        self.a_zero_never_carries_a_minus_sign()
        self.days_are_whole_days_in_india()
        self.the_summary_counts_each_broker()
        self.writing_replaces_the_days_in_one_transaction()
        self.a_failed_write_rolls_back()
        self.legs_are_sorted_into_the_selectors_categories()
        self.the_latency_cost_is_the_mean_over_every_leg()
        self.too_few_legs_leave_a_figure_unmeasured()
        self.the_answer_time_is_the_median()
        self.only_measured_figures_are_written()
        self.the_window_reaches_twenty_days_back()

        total = self.passed + len(self.failed)
        print(f'{total - len(self.failed)}/{total} checks passed.')
        if self.failed:
            return 1
        return 0

    def a_buy_that_walked_the_book(self):
        """A buy decided at a mid of 238.25 and filled at 238.90 is split into delay, latency, half spread and impact.

        Returns:
            None: This method returns nothing.
        """
        measurement, costs = self.measured(self.database())
        row = costs[('buy', '1')].row()
        self.check('buy decision mid', row['decision_mid'], decimal.Decimal('238.2500'))
        self.check('buy delay', row['delay_cost'], decimal.Decimal('0.1000'))
        self.check('buy latency', row['latency_cost'], decimal.Decimal('0.1000'))
        self.check('buy half spread', row['half_spread_cost'], decimal.Decimal('0.2500'))
        self.check('buy beyond the touch', row['beyond_touch_cost'], decimal.Decimal('0.2000'))
        self.check('buy total', row['total_cost'], decimal.Decimal('0.6500'))
        self.check('buy basis points', row['total_cost_basis_points'], decimal.Decimal('27.28'))
        self.check('buy latency basis points', row['latency_cost_basis_points'], decimal.Decimal('4.20'))
        self.check('buy rupees', row['total_cost_rupees'], decimal.Decimal('42.25'))
        parts = row['delay_cost'] + row['latency_cost'] + row['half_spread_cost'] + row['beyond_touch_cost']
        self.check('buy parts add up to the total', parts, row['total_cost'])
        self.check('buy decided at the parent arrival', row['decided_at'], self.moment(10, 15, 0, 0))
        self.check('buy quote times', (row['decision_quote_time'], row['send_quote_time'], row['answer_quote_time']), (self.moment(10, 14, 59, 900), self.moment(10, 15, 0, 150), self.moment(10, 15, 0, 250)))

    def a_sell_turns_every_sign(self):
        """A sell gains when the price rises, so the same moves count against it the other way.

        Returns:
            None: This method returns nothing.
        """
        measurement, costs = self.measured(self.database())
        row = costs[('sell', '1')].row()
        self.check('sell delay', row['delay_cost'], decimal.Decimal('-0.1000'))
        self.check('sell latency', row['latency_cost'], decimal.Decimal('-0.1000'))
        self.check('sell half spread', row['half_spread_cost'], decimal.Decimal('0.2500'))
        self.check('sell beyond the touch', row['beyond_touch_cost'], decimal.Decimal('0.1500'))
        self.check('sell total', row['total_cost'], decimal.Decimal('0.2000'))

    def a_resting_order_filled_inside_the_spread(self):
        """A buy filled at the bid earns the spread back, so its beyond-the-touch part is negative.

        Returns:
            None: This method returns nothing.
        """
        leg = LegExecution('resting', '1', self.moment(10, 15, 0))
        leg.transaction_type = 'BUY'
        leg.average_price = decimal.Decimal('238.20')
        leg.filled_quantity = 65
        quote = QuoteMoment(self.moment(10, 15, 0), decimal.Decimal('238.20'), decimal.Decimal('238.70'))
        cost = ExecutionCost(leg, quote, quote, quote, 'nse_equity_index_options', True)
        self.check('resting half spread', cost.half_spread(), decimal.Decimal('0.25'))
        self.check('resting beyond the touch', cost.beyond_touch(), decimal.Decimal('-0.50'))
        self.check('resting total', cost.total(), decimal.Decimal('-0.25'))

    def a_later_leg_is_measured_from_its_own_request(self):
        """A stop sent five minutes after its parent arrived is measured from when it was sent, so it has no delay.

        Returns:
            None: This method returns nothing.
        """
        measurement, costs = self.measured(self.database())
        row = costs[('buy', '2')].row()
        self.check('stop decided when it was sent', row['decided_at'], self.moment(10, 20, 0, 0))
        self.check('stop has no delay', row['delay_cost'], decimal.Decimal('0.0000'))
        self.check('stop total', row['total_cost'], decimal.Decimal('0.3000'))

    def a_fill_is_read_across_several_updates(self):
        """The quantity and the price can arrive on different update rows, and the last of each counts.

        Returns:
            None: This method returns nothing.
        """
        measurement, costs = self.measured(self.database())
        leg = costs[('buy', '1')].leg
        self.check('fill quantity and price', (leg.filled_quantity, leg.average_price), (65, decimal.Decimal('238.90')))

    def an_old_quote_counts_as_missing(self):
        """A quote two minutes old leaves every part empty, but the leg is still written.

        Returns:
            None: This method returns nothing.
        """
        measurement, costs = self.measured(self.database())
        row = costs[('stale', '1')].row()
        self.check('stale total', row['total_cost'], None)
        self.check('stale basis points', row['total_cost_basis_points'], None)
        self.check('stale quote time', row['decision_quote_time'], None)

    def a_one_sided_book_is_not_a_quote(self):
        """A tick with no bid, received after the answer quote but before the broker answered, is passed over for the one before it.

        Returns:
            None: This method returns nothing.
        """
        database = StandInExecutionDatabase()
        database.add_tick(OPTION, self.moment(10, 15, 0, 250), '238.20', '238.70')
        database.add_tick(OPTION, self.moment(10, 15, 0, 270), None, '238.70')
        found = database.quote_at(OPTION, self.moment(10, 15, 0, 300), self.moment(10, 14, 0))
        self.check('two-sided tick chosen', found[0], self.moment(10, 15, 0, 250))

    def unfilled_legs_and_other_days_are_left_out(self):
        """A rejected leg is never measured, and a leg sent the day before is measured only when that day is asked for.

        Returns:
            None: This method returns nothing.
        """
        measurement, costs = self.measured(self.database())
        self.check('legs of one day', sorted(costs), [
            ('buy', '1'),
            ('buy', '2'),
            ('crude', '1'),
            ('sell', '1'),
            ('stale', '1'),
        ])
        measurement, costs = self.measured(self.database(), day_count=2)
        self.check('yesterday included over two days', ('yesterday', '1') in costs, True)
        self.check('yesterday total', costs[('yesterday', '1')].row()['total_cost'], decimal.Decimal('0.1000'))

    def a_commodity_fill_has_no_rupee_total(self):
        """A commodity fill may be counted in lots, so its rupee total is left empty while its basis points are kept.

        Returns:
            None: This method returns nothing.
        """
        measurement, costs = self.measured(self.database())
        row = costs[('crude', '1')].row()
        self.check('crude rupees', row['total_cost_rupees'], None)
        self.check('crude basis points', row['total_cost_basis_points'], decimal.Decimal('2.88'))
        self.check('crude broker', row['broker'], 'zerodha')

    def a_zero_never_carries_a_minus_sign(self):
        """A sell whose mid-price did not move has a latency of plain zero, not minus zero.

        Returns:
            None: This method returns nothing.
        """
        leg = LegExecution('flat', '1', self.moment(10, 15, 0))
        leg.transaction_type = 'SELL'
        leg.average_price = decimal.Decimal('238.20')
        leg.filled_quantity = 65
        quote = QuoteMoment(self.moment(10, 15, 0), decimal.Decimal('238.20'), decimal.Decimal('238.70'))
        row = ExecutionCost(leg, quote, quote, quote, 'nse_equity_index_options', True).row()
        self.check('latency written as zero', str(row['latency_cost']), '0.0000')
        self.check('latency basis points written as zero', str(row['latency_cost_basis_points']), '0.00')

    def days_are_whole_days_in_india(self):
        """Two days ending on 6 October run from midnight on the 5th to midnight on the 7th, India time.

        Returns:
            None: This method returns nothing.
        """
        measurement = ExecutionCostMeasurement(None, self.logger)
        start, end = measurement.day_bounds(DAY, 2)
        self.check('start', start, self.moment(0, 0, 0, 0, datetime.date(2026, 10, 5)))
        self.check('end', end, self.moment(0, 0, 0, 0, datetime.date(2026, 10, 7)))

    def the_summary_counts_each_broker(self):
        """The summary counts every leg, and only legs with a decision quote in the figures.

        Returns:
            None: This method returns nothing.
        """
        measurement, costs = self.measured(self.database())
        summary = measurement.summary(list(costs.values()))
        self.check('summary brokers', [summary[0]['broker'], summary[1]['broker']], ['flattrade', 'zerodha'])
        self.check('flattrade legs and measured', (summary[0]['legs'], summary[0]['measured']), (4, 3))
        self.check('flattrade mean latency', summary[0]['mean_latency_basis_points'], decimal.Decimal('0.00'))
        self.check('zerodha median', summary[1]['median_total_basis_points'], decimal.Decimal('2.88'))

    def writing_replaces_the_days_in_one_transaction(self):
        """A write applies the table's file, deletes the days, inserts every row and commits.

        Returns:
            None: This method returns nothing.
        """
        database = self.database()
        measurement = ExecutionCostMeasurement(database.connect, self.logger)
        start, end = measurement.day_bounds(DAY, 1)
        costs = measurement.measure(start, end)
        database.statements = []
        database.transactions = []
        written = measurement.write(start, end, costs)
        self.check('rows written', written, 5)
        self.check('statements', database.statements, [
            'DDL',
            'DELETE',
            'INSERT',
        ])
        self.check('deleted days', database.deleted_between, [(start, end)])
        self.check('committed once', database.transactions, ['COMMIT'])
        first = dict(zip(COST_COLUMNS, database.inserted[0]))
        self.check('first row is the first leg sent', (first['parent_order_id'], first['leg_id']), ('buy', '1'))

    def a_failed_write_rolls_back(self):
        """An insert that fails rolls the delete back too, and the error reaches the caller.

        Returns:
            None: This method returns nothing.
        """
        database = self.database()
        database.fail_on_insert = True
        measurement = ExecutionCostMeasurement(database.connect, self.logger)
        start, end = measurement.day_bounds(DAY, 1)
        costs = measurement.measure(start, end)
        database.transactions = []
        raised = False
        try:
            measurement.write(start, end, costs)
        except RuntimeError:
            raised = True
        self.check('error raised', raised, True)
        self.check('rolled back', database.transactions, ['ROLLBACK'])


    def latency_rows(self, broker, count, latency_costs=None, answer_milliseconds='60', segment='nse_equity_index_options', product='MIS'):
        """Rows of the execution cost table for one broker, as the calibration reads them.

        Args:
            broker (str): The broker.
            count (int): How many rows.
            latency_costs (list | None): The latency costs (str) of the first rows; the rest are zero.
            answer_milliseconds (str): Every row's answer time.
            segment (str): Every row's segment.
            product (str): Every row's product.

        Returns:
            list: The rows, as tuples.
        """
        given = list(latency_costs or [])
        rows = []
        for index in range(count):
            latency_cost = decimal.Decimal('0')
            if index < len(given):
                latency_cost = decimal.Decimal(given[index])
            rows.append((broker, segment, product, latency_cost, decimal.Decimal(answer_milliseconds)))
        return rows

    def legs_are_sorted_into_the_selectors_categories(self):
        """A future or option is `fno` whatever its product, a `CNC` order otherwise is `delivery`, and anything else is `intraday`.

        Returns:
            None: This method returns nothing.
        """
        calibration = LatencyCalibration(None, self.logger)
        cases = [
            (('nse_equity_index_options', 'MIS'), 'fno'),
            (('mcx_commodity_futures', 'NRML'), 'fno'),
            (('nse_equities', 'CNC'), 'delivery'),
            (('nse_equities', 'MIS'), 'intraday'),
            ((None, 'MIS'), 'intraday'),
        ]
        for (segment, product), expected in cases:
            self.check(f'category of {segment} {product}', calibration.category(segment, product), expected)

    def the_latency_cost_is_the_mean_over_every_leg(self):
        """Twenty-six legs that saw no move and four that did average to half a basis point; dropping the extremes would have given zero.

        Returns:
            None: This method returns nothing.
        """
        calibration = LatencyCalibration(None, self.logger)
        rows = self.latency_rows('zerodha', 30, ['3.00', '3.00', '-1.00', '10.00'])
        brokers = calibration.brokers_from(rows)
        self.check('fno latency cost', brokers[0].latency_cost('fno'), decimal.Decimal('0.50'))
        self.check('fno legs', brokers[0].leg_count('fno'), 30)
        flat = calibration.brokers_from(self.latency_rows('zerodha', 30, ['-0.00']))
        self.check('no move is plain zero', str(flat[0].latency_cost('fno')), '0.00')

    def too_few_legs_leave_a_figure_unmeasured(self):
        """With 29 legs a category is not measured, and a broker with nothing measured is not written at all.

        Returns:
            None: This method returns nothing.
        """
        calibration = LatencyCalibration(None, self.logger)
        brokers = calibration.brokers_from(self.latency_rows('dhan', 29, ['5.00']))
        self.check('29 legs give no figure', brokers[0].latency_cost('fno'), None)
        self.check('29 answers give no time', brokers[0].typical_answer_milliseconds(), None)
        self.check('nothing measured', brokers[0].measured_anything(), False)

    def the_answer_time_is_the_median(self):
        """Fifteen answers in 50 ms and fifteen in 70 ms give a median of 60 ms.

        Returns:
            None: This method returns nothing.
        """
        calibration = LatencyCalibration(None, self.logger)
        rows = self.latency_rows('flattrade', 15, answer_milliseconds='50') + self.latency_rows('flattrade', 15, answer_milliseconds='70')
        brokers = calibration.brokers_from(rows)
        self.check('median answer time', brokers[0].typical_answer_milliseconds(), decimal.Decimal('60'))

    def only_measured_figures_are_written(self):
        """A broker with enough legs is updated with None for its unmeasured categories, one without is skipped, and one missing from the cost table is warned about.

        Returns:
            None: This method returns nothing.
        """
        database = StandInExecutionDatabase()
        database.cost_table_brokers = [
            'flattrade',
            'dhan',
        ]
        database.cost_rows = (
            self.latency_rows('flattrade', 30, ['2.00'])
            + self.latency_rows('dhan', 10)
            + self.latency_rows('newbroker', 30, segment='nse_equities', product='CNC')
        )
        calibration = LatencyCalibration(database.connect, self.logger)
        brokers = calibration.measure(calibration.window_start(self.moment(23, 50, 0)))
        updated = calibration.write(brokers)
        self.check('rows updated', updated, 1)
        self.check('updates sent', database.updates, [
            (None, None, decimal.Decimal('0.07'), decimal.Decimal('60'), 'flattrade'),
            (None, decimal.Decimal('0.00'), None, decimal.Decimal('60'), 'newbroker'),
        ])
        self.check('read rolled back, write committed', database.transactions, [
            'ROLLBACK',
            'COMMIT',
        ])

    def the_window_reaches_twenty_days_back(self):
        """The default window starts twenty days before the run.

        Returns:
            None: This method returns nothing.
        """
        calibration = LatencyCalibration(None, self.logger)
        start = calibration.window_start(self.moment(23, 50, 0))
        self.check('window start', start, self.moment(23, 50, 0, 0, datetime.date(2026, 9, 16)))


if __name__ == '__main__':
    sys.exit(ExecutionCostsSuite().run())
