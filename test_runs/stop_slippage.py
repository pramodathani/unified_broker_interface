"""Offline checks of the stop slippage measurement, the slip allowance and the tripwire price.

The events are scripted on a stand-in database in the shapes the order engine wrote on 19 October 2026: a held stop on a NIFTY option whose trigger fired and whose own order filled, one that was cancelled and closed by a separate order, and the cases the measurement must leave out. The expected figures were worked out by hand and with plain floating point outside the code under test. No PostgreSQL, Redis, credentials or network are used.

Typical usage:

    python -m test_runs.stop_slippage
"""

import datetime
import decimal
import logging
import sys

from test_runs.stop_slippage_stand_ins import StandInStopDatabase
from unified_broker_interface.utilities.execution_costs.breakeven_price import (
    BreakevenPrice,
)
from unified_broker_interface.utilities.execution_costs.charge_rate_table import (
    ChargeRate,
)
from unified_broker_interface.utilities.execution_costs.stop_outcome import (
    StopOutcome,
)
from unified_broker_interface.utilities.execution_costs.stop_slip_allowance import (
    StopSlipAllowance,
)
from unified_broker_interface.utilities.execution_costs.stop_slippage_measurement import (
    StopSlippageMeasurement,
)
from unified_broker_interface.utilities.execution_costs.tripwire_price import (
    TripwirePrice,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
OPTION = '065e67b5-b3f8-5374-a0bb-4ddc7786338d'
OTHER_OPTION = '0180a843-ec35-5e61-b0a2-31e2b02bbaf9'
SEGMENT = 'nse_equity_index_options'
DAY = datetime.date(2026, 10, 19)


class StopSlippageSuite:
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
        self.logger = logging.getLogger('test_runs.stop_slippage')
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

    def moment(self, hour, minute, second=0):
        """A moment on 19 October 2026 in India.

        Args:
            hour (int): The hour.
            minute (int): The minute.
            second (int): The second.

        Returns:
            datetime.datetime: The moment.
        """
        return datetime.datetime(2026, 10, 19, hour, minute, second, tzinfo=INDIA)

    def option_rate(self):
        """The NSE index option charge row.

        Returns:
            ChargeRate: The row.
        """
        return ChargeRate(SEGMENT, 'fno', decimal.Decimal('0'), decimal.Decimal('0.0015'), decimal.Decimal('0.0003553'), decimal.Decimal('0.000001'), decimal.Decimal('0.00003'), decimal.Decimal('0.18'))

    def scripted_day(self):
        """A day with every kind of stop the measurement must tell apart.

        Returns:
            StandInStopDatabase: The database.
        """
        database = StandInStopDatabase()
        database.segments[OPTION] = SEGMENT
        database.segments[OTHER_OPTION] = SEGMENT
        database.add_stop(self.moment(13, 26, 25), 'filled-by-stop', OPTION, '196.15', fill_price='195.15')
        database.add_stop(self.moment(13, 12, 3), 'closed-by-order', OPTION, '196.15')
        database.add_order(self.moment(13, 12, 6), 'other-instrument-close', OTHER_OPTION, 'SELL', fill_price='150.00')
        database.add_order(self.moment(13, 12, 5), 'wrong-side-order', OPTION, 'BUY', fill_price='190.00')
        database.add_order(self.moment(13, 12, 7), 'program-close', OPTION, 'SELL', fill_price='194.60')
        database.add_stop(self.moment(14, 0, 0), 'never-closed', OTHER_OPTION, '161.25')
        database.add_order(self.moment(14, 1, 30), 'too-late-close', OTHER_OPTION, 'SELL', fill_price='160.00')
        database.add_stop(self.moment(14, 30, 0), 'buy-stop', OTHER_OPTION, '100.00', direction='at_or_above', fill_price='100.30')
        database.add_stop(self.moment(9, 0, 0) - datetime.timedelta(days=1), 'yesterday', OPTION, '180.00', fill_price='179.00')
        database.add_event(self.moment(15, 0, 0), 'not-fired', 'parent_received', synthetic_type='plan', instrument_id=OPTION, detail={'parameters': {'plan': {'order': {'side': 'protect', 'trigger': {'price_crosses': {'field': 'bid', 'level': 170.0, 'direction': 'at_or_below'}}}}}})
        database.add_event(self.moment(15, 5, 0), 'entry-plan', 'parent_received', synthetic_type='plan', instrument_id=OPTION, detail={'parameters': {'plan': {'order': {'side': 'entry', 'trigger': {'price_crosses': {'field': 'ask', 'level': 170.0, 'direction': 'at_or_above'}}}}}})
        database.add_event(self.moment(15, 5, 1), 'entry-plan', 'parameters_changed', synthetic_type='plan', detail={'parameters': {'parts': {'root': {'memory': {'trigger': {'fired': True}}}}}})
        return database

    def measured(self):
        """Measures the scripted day.

        Returns:
            tuple: The `StopSlippageMeasurement`, the outcomes (list) by parent order id in a dict, and the `StandInStopDatabase`.
        """
        database = self.scripted_day()
        measurement = StopSlippageMeasurement(database.connect, self.logger)
        start, end = measurement.day_bounds(DAY, 1)
        outcomes = measurement.measure(start, end)
        by_parent = {}
        for outcome in outcomes:
            by_parent[outcome.parent_order_id] = outcome
        return measurement, outcomes, by_parent, database

    def run(self):
        """Runs every check and prints how many passed.

        Returns:
            int: 0 when every check passed, 1 when any failed.
        """
        self.only_fired_protective_stops_of_the_day_count()
        self.a_stop_filled_by_its_own_order()
        self.a_stop_closed_by_the_programs_own_order()
        self.a_close_too_late_is_not_found()
        self.a_buy_stop_slips_upwards()
        self.the_brokers_record_comes_before_another_order()
        self.broker_fills_are_averaged_and_skipped_without_the_table()
        self.a_fired_flag_without_a_time_uses_the_events_time()
        self.the_write_replaces_the_days_rows()
        self.the_summary_counts_each_kind_of_close()
        self.an_outcome_without_a_close()
        self.the_allowance_needs_thirty_stops()
        self.the_allowance_is_the_nearest_rank_percentile()
        self.the_allowance_reads_the_table()
        self.a_tripwire_from_the_measured_slip()
        self.a_tripwire_from_the_spread()
        self.a_tripwire_fill_at_the_allowance_lands_on_the_floor()
        self.a_tripwire_needs_an_allowance_or_a_spread()

        total = self.passed + len(self.failed)
        print(f'{total - len(self.failed)}/{total} checks passed.')
        if self.failed:
            return 1
        return 0

    def only_fired_protective_stops_of_the_day_count(self):
        """Yesterday's stop, a stop that never fired and a fired entry plan are left out, and the rest come in firing order.

        Returns:
            None: This method returns nothing.
        """
        measurement, outcomes, by_parent, database = self.measured()
        del measurement
        del database
        order = []
        for outcome in outcomes:
            order.append(outcome.parent_order_id)
        self.check('fired stops in order', order, ['closed-by-order', 'filled-by-stop', 'never-closed', 'buy-stop'])
        self.check('segment filled in', by_parent['filled-by-stop'].segment, SEGMENT)

    def a_stop_filled_by_its_own_order(self):
        """A sell stop at 196.15 whose order filled at 195.15 slipped by 1.00, or 50.98 basis points.

        Returns:
            None: This method returns nothing.
        """
        outcome = self.measured()[2]['filled-by-stop']
        self.check('own fill: closed by', outcome.closed_by, 'stop')
        self.check('own fill: slip', (outcome.slip(), outcome.slip_basis_points()), (decimal.Decimal('1.0000'), decimal.Decimal('50.98')))
        self.check('own fill: side and field', (outcome.transaction_type, outcome.trigger_field), ('SELL', 'bid'))

    def a_stop_closed_by_the_programs_own_order(self):
        """A stop that did not fill is closed by the first sell on the same instrument within a minute, 194.60, not by a buy or another instrument's sell.

        Returns:
            None: This method returns nothing.
        """
        outcome = self.measured()[2]['closed-by-order']
        self.check('other order: closed by', outcome.closed_by, 'other_order')
        self.check('other order: price', outcome.average_price, decimal.Decimal('194.60'))
        self.check('other order: slip', (outcome.slip(), outcome.slip_basis_points()), (decimal.Decimal('1.5500'), decimal.Decimal('79.02')))

    def a_close_too_late_is_not_found(self):
        """A sell ninety seconds after the stop fired is not its close, so the stop stays unresolved.

        Returns:
            None: This method returns nothing.
        """
        outcome = self.measured()[2]['never-closed']
        self.check('unresolved', (outcome.is_resolved(), outcome.closed_by, outcome.slip(), outcome.slip_basis_points()), (False, None, None, None))

    def a_buy_stop_slips_upwards(self):
        """A buy stop at 100.00 that filled at 100.30 slipped by 0.30, or 30 basis points.

        Returns:
            None: This method returns nothing.
        """
        outcome = self.measured()[2]['buy-stop']
        self.check('buy stop: side', outcome.transaction_type, 'BUY')
        self.check('buy stop: slip', (outcome.slip(), outcome.slip_basis_points()), (decimal.Decimal('0.3000'), decimal.Decimal('30.00')))

    def the_brokers_record_comes_before_another_order(self):
        """A stop whose fill the engine never saw, but which the broker's final record shows filled at 195.85, is closed by the stop and not by the strategy's later sell.

        Returns:
            None: This method returns nothing.
        """
        database = self.scripted_day()
        database.daily_orders_exist = True
        database.broker_fills.append(('closed-by-order', 65, '195.85'))
        measurement = StopSlippageMeasurement(database.connect, self.logger)
        start, end = measurement.day_bounds(DAY, 1)
        by_parent = {}
        for outcome in measurement.measure(start, end):
            by_parent[outcome.parent_order_id] = outcome
        outcome = by_parent['closed-by-order']
        self.check('broker record: closed by', (outcome.closed_by, outcome.average_price, outcome.slip()), ('stop', decimal.Decimal('195.85'), decimal.Decimal('0.3000')))
        self.check('broker record: own fill still wins', by_parent['filled-by-stop'].average_price, decimal.Decimal('195.15'))

    def broker_fills_are_averaged_and_skipped_without_the_table(self):
        """Two broker fills of one stop average by quantity, and nothing is read when the table does not exist.

        Returns:
            None: This method returns nothing.
        """
        database = StandInStopDatabase()
        database.daily_orders_exist = True
        database.broker_fills.append(('stop', 40, '100.00'))
        database.broker_fills.append(('stop', 25, '99.48'))
        measurement = StopSlippageMeasurement(database.connect, self.logger)
        cursor = database.connect().cursor()
        self.check('averaged', measurement.read_broker_fills(cursor, ['stop']), {'stop': (65, decimal.Decimal('99.8'))})
        self.check('no parents', measurement.read_broker_fills(cursor, []), {})
        database.daily_orders_exist = False
        self.check('no table', measurement.read_broker_fills(cursor, ['stop']), {})

    def a_fired_flag_without_a_time_uses_the_events_time(self):
        """A part that says only that its trigger fired is taken to have fired when the event was written.

        Returns:
            None: This method returns nothing.
        """
        database = StandInStopDatabase()
        measurement = StopSlippageMeasurement(database.connect, self.logger)
        moment = self.moment(10, 0, 0)
        row = {'time': moment, 'detail': {'parameters': {'parts': {'root': {'memory': {'trigger': {'fired': True}}}}}}}
        self.check('fired flag', measurement.fired_at(row), moment)
        waiting = {'time': moment, 'detail': {'parameters': {'parts': {'root': {'memory': {'trigger': {'first': {}}}}}}}}
        self.check('not fired', measurement.fired_at(waiting), None)

    def the_write_replaces_the_days_rows(self):
        """Writing runs the DDL, deletes the day and inserts one row per stop with the columns in order.

        Returns:
            None: This method returns nothing.
        """
        measurement, outcomes, by_parent, database = self.measured()
        del by_parent
        start, end = measurement.day_bounds(DAY, 1)
        written = measurement.write(start, end, outcomes)
        self.check('write: count', written, 4)
        self.check('write: delete bounds', database.deleted, [(start, end)])
        self.check('write: DDL first', database.statements[-3:], ['CREATE', 'DELETE', 'INSERT'])
        first = database.written[0]
        self.check('write: first row', (first[1], first[4], first[6], first[7], first[10]), ('closed-by-order', 'SELL', decimal.Decimal('196.15'), 'other_order', decimal.Decimal('1.5500')))

    def the_summary_counts_each_kind_of_close(self):
        """The sell line counts one close by the stop, one by another order and one unresolved, with a median of 64.99 basis points.

        Returns:
            None: This method returns nothing.
        """
        measurement, outcomes, by_parent, database = self.measured()
        del by_parent
        del database
        lines = measurement.summary(outcomes)
        self.check('summary: lines', len(lines), 2)
        sell = lines[1]
        figures = (sell['transaction_type'], sell['fired'], sell['by_stop'], sell['by_other_order'], sell['unresolved'])
        self.check('summary: sell counts', figures, ('SELL', 3, 1, 1, 1))
        self.check('summary: sell slips', (sell['median_slip_basis_points'], sell['ninetieth_slip_basis_points']), (decimal.Decimal('65.00'), decimal.Decimal('79.02')))

    def an_outcome_without_a_close(self):
        """A fresh outcome has no close, and its row says so.

        Returns:
            None: This method returns nothing.
        """
        outcome = StopOutcome('stop', OPTION, SEGMENT, 'SELL', 'bid', '196.15', self.moment(13, 0))
        row = outcome.row()
        self.check('fresh row', (row['closed_by'], row['average_price'], row['slip'], row['slip_basis_points']), (None, None, None, None))
        outcome.record_close('stop', 65, '196.15')
        self.check('fill at the trigger', (outcome.slip(), outcome.slip_fraction()), (decimal.Decimal('0.0000'), decimal.Decimal('0')))

    def the_allowance_needs_thirty_stops(self):
        """Twenty-nine measured stops give no allowance; thirty do.

        Returns:
            None: This method returns nothing.
        """
        values = []
        for index in range(29):
            values.append(decimal.Decimal(index))
        allowance = StopSlipAllowance({(SEGMENT, 'SELL'): values})
        self.check('29 stops', (allowance.stop_count(SEGMENT, 'SELL'), allowance.basis_points(SEGMENT, 'SELL')), (29, None))
        values.append(decimal.Decimal(29))
        allowance = StopSlipAllowance({(SEGMENT, 'SELL'): values})
        self.check('30 stops', allowance.basis_points(SEGMENT, 'SELL') is not None, True)
        self.check('other side', allowance.fraction(SEGMENT, 'BUY'), None)

    def the_allowance_is_the_nearest_rank_percentile(self):
        """Of the slips 1 to 40, the 90th percentile is 36, the 50th is 20, and an allowance below zero is zero.

        Returns:
            None: This method returns nothing.
        """
        values = []
        for index in range(40, 0, -1):
            values.append(decimal.Decimal(index))
        allowance = StopSlipAllowance({(SEGMENT, 'SELL'): values})
        self.check('90th', allowance.basis_points(SEGMENT, 'SELL'), decimal.Decimal(36))
        self.check('50th', allowance.basis_points(SEGMENT, 'SELL', 50), decimal.Decimal(20))
        self.check('as a share', allowance.fraction(SEGMENT, 'SELL'), decimal.Decimal('0.0036'))
        negative = []
        for index in range(30):
            negative.append(decimal.Decimal(-5))
        self.check('below zero', StopSlipAllowance({(SEGMENT, 'SELL'): negative}).basis_points(SEGMENT, 'SELL'), decimal.Decimal(0))

    def the_allowance_reads_the_table(self):
        """`read` groups the table's slips by segment and side.

        Returns:
            None: This method returns nothing.
        """
        database = StandInStopDatabase()
        for index in range(30):
            database.slips.append((SEGMENT, 'SELL', decimal.Decimal(index)))
        database.slips.append((SEGMENT, 'BUY', decimal.Decimal('3')))
        allowance = StopSlipAllowance()
        allowance.read(database.connect, self.moment(23, 50))
        self.check('read: counts', (allowance.stop_count(SEGMENT, 'SELL'), allowance.stop_count(SEGMENT, 'BUY')), (30, 1))
        self.check('read: 90th', allowance.basis_points(SEGMENT, 'SELL'), decimal.Decimal(26))

    def a_tripwire_from_the_measured_slip(self):
        """With 19 October's 58.03 basis points, an option bought at 177.00 gets a tripwire of 178.50 over a floor of 177.45, and one sold gets 175.50 under 176.55.

        Returns:
            None: This method returns nothing.
        """
        share = decimal.Decimal('0.005803')
        bought = TripwirePrice(BreakevenPrice(self.option_rate(), 'BUY', '177', 65, 0, '0.05'), share)
        sold = TripwirePrice(BreakevenPrice(self.option_rate(), 'SELL', '177', 65, 0, '0.05'), share)
        self.check('bought: exact and price', (bought.exact_price(), bought.price()), (decimal.Decimal('178.4858'), decimal.Decimal('178.50')))
        self.check('bought: distances', (bought.distance_from_floor(), bought.distance_from_entry()), (decimal.Decimal('1.05'), decimal.Decimal('1.50')))
        self.check('sold: exact and price', (sold.exact_price(), sold.price()), (decimal.Decimal('175.5313'), decimal.Decimal('175.50')))
        self.check('sold: distances', (sold.distance_from_floor(), sold.distance_from_entry()), (decimal.Decimal('1.05'), decimal.Decimal('1.50')))
        self.check('source', bought.source(), 'measured')

    def a_tripwire_from_the_spread(self):
        """With no measured slip, a spread of 0.20 and two ticks put the tripwire 0.30 beyond the floor.

        Returns:
            None: This method returns nothing.
        """
        bought = TripwirePrice(BreakevenPrice(self.option_rate(), 'BUY', '177', 65, 0, '0.05'), spread='0.20')
        sold = TripwirePrice(BreakevenPrice(self.option_rate(), 'SELL', '177', 65, 0, '0.05'), spread='0.20')
        self.check('spread: bought', (bought.price(), bought.source()), (decimal.Decimal('177.75'), 'spread'))
        self.check('spread: sold', sold.price(), decimal.Decimal('176.25'))
        self.check('measured wins over spread', TripwirePrice(BreakevenPrice(self.option_rate(), 'BUY', '177', 65, 0, '0.05'), decimal.Decimal('0.005803'), '0.20').source(), 'measured')

    def a_tripwire_fill_at_the_allowance_lands_on_the_floor(self):
        """For several allowances and both sides, a fill slipping by exactly the allowance from the tripwire is never on the wrong side of the floor.

        Returns:
            None: This method returns nothing.
        """
        for share in ('0', '0.001', '0.005803', '0.0125'):
            for opening_side in ('BUY', 'SELL'):
                breakeven = BreakevenPrice(self.option_rate(), opening_side, '177', 65, 20, '0.05')
                tripwire = TripwirePrice(breakeven, decimal.Decimal(share))
                fraction = decimal.Decimal(share)
                if opening_side == 'BUY':
                    fill = tripwire.price() * (1 - fraction)
                    safe = fill >= breakeven.price()
                else:
                    fill = tripwire.price() * (1 + fraction)
                    safe = fill <= breakeven.price()
                self.check(f'lands on the floor: {opening_side} {share}', safe, True)

    def a_tripwire_needs_an_allowance_or_a_spread(self):
        """No allowance and no spread, or an allowance of one or more, raises ValueError.

        Returns:
            None: This method returns nothing.
        """
        breakeven = BreakevenPrice(self.option_rate(), 'BUY', '177', 65)
        for share, spread in ((None, None), (decimal.Decimal(1), None)):
            try:
                TripwirePrice(breakeven, share, spread)
            except ValueError:
                self.check(f'refused: {share} {spread}', True, True)
                continue
            self.check(f'refused: {share} {spread}', False, True)


if __name__ == '__main__':
    sys.exit(StopSlippageSuite().run())
