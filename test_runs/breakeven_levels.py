"""Offline checks of the price flicker, the switch-on price and the breakeven levels service.

The ticks are scripted around a NIFTY option near 177 on 19 October 2026, and the charge rates, broker costs and stop slips are built in memory, so no PostgreSQL, Redis, credentials or network are used. The expected figures were worked out by hand outside the code under test.

Typical usage:

    python -m test_runs.breakeven_levels
"""

import datetime
import decimal
import logging
import sys

from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCostTable,
    BrokerCosts,
)
from unified_broker_interface.utilities.execution_costs.breakeven_levels import (
    BreakevenLevels,
    BreakevenLevelsError,
)
from unified_broker_interface.utilities.execution_costs.breakeven_price import (
    BreakevenPrice,
)
from unified_broker_interface.utilities.execution_costs.charge_rate_table import (
    ChargeRate,
    ChargeRateTable,
)
from unified_broker_interface.utilities.execution_costs.price_flicker import (
    PriceFlicker,
)
from unified_broker_interface.utilities.execution_costs.stop_slip_allowance import (
    StopSlipAllowance,
)
from unified_broker_interface.utilities.execution_costs.switch_on_price import (
    SwitchOnPrice,
)
from unified_broker_interface.utilities.execution_costs.tripwire_price import (
    TripwirePrice,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
OPTION = 'b546e617-303e-53d7-b888-3fd0256bafad'
SEGMENT = 'nse_equity_index_options'
START = datetime.datetime(2026, 10, 19, 15, 10, tzinfo=INDIA)


class StandInTickDatabase:
    """A database stand-in that answers the tick query with scripted rows and the stop slip query with scripted slips.

    Attributes:
        ticks (list): Tuples of time, bid and ask.
        slips (list): Tuples of segment, side and slip in basis points.
        tick_reads (int): How many times the ticks were read.
    """

    def __init__(self, ticks=None, slips=None):
        """Builds the database.

        Args:
            ticks (list | None): The tick rows.
            slips (list | None): The slip rows.

        Returns:
            None: This method returns nothing.
        """
        self.ticks = list(ticks or [])
        self.slips = list(slips or [])
        self.tick_reads = 0
        self.answer = []

    def connect(self):
        """Opens a connection, which is this object.

        Returns:
            StandInTickDatabase: This object.
        """
        return self

    def cursor(self):
        """A cursor, which is this object.

        Returns:
            StandInTickDatabase: This object.
        """
        return self

    def __enter__(self):
        """Enters the `with` block.

        Returns:
            StandInTickDatabase: This object.
        """
        return self

    def __exit__(self, error_type, error, traceback):
        """Leaves the `with` block without suppressing an exception.

        Args:
            error_type (type | None): The exception's type.
            error (BaseException | None): The exception.
            traceback (types.TracebackType | None): The traceback.

        Returns:
            bool: False.
        """
        del error_type
        del error
        del traceback
        return False

    def execute(self, statement, parameters=None):
        """Answers the tick query or the slip query.

        Args:
            statement (str): The SQL.
            parameters (tuple | None): Its parameters.

        Returns:
            None: This method returns nothing.
        """
        del parameters
        if 'FROM unified.ticks' in statement:
            self.tick_reads = self.tick_reads + 1
            self.answer = list(self.ticks)
        elif 'FROM unified.stop_slippage' in statement:
            self.answer = list(self.slips)
        else:
            self.answer = []

    def fetchall(self):
        """The last answer.

        Returns:
            list: The rows.
        """
        return self.answer

    def rollback(self):
        """Rolls back nothing.

        Returns:
            None: This method returns nothing.
        """

    def close(self):
        """Closes nothing.

        Returns:
            None: This method returns nothing.
        """


class LoadedChargeRateTable(ChargeRateTable):
    """A charge rate table whose `load` keeps the rows it was given instead of reading the database."""

    def load(self):
        """Keeps the rows given.

        Returns:
            None: This method returns nothing.
        """


class LoadedBrokerCostTable(BrokerCostTable):
    """A broker cost table whose `load` keeps the rows it was given instead of reading the database."""

    def load(self):
        """Keeps the rows given.

        Returns:
            None: This method returns nothing.
        """


class BreakevenLevelsSuite:
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
        self.logger = logging.getLogger('test_runs.breakeven_levels')
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

    def option_rate(self):
        """The NSE index option charge row.

        Returns:
            ChargeRate: The row.
        """
        return ChargeRate(SEGMENT, 'fno', decimal.Decimal('0'), decimal.Decimal('0.0015'), decimal.Decimal('0.0003553'), decimal.Decimal('0.000001'), decimal.Decimal('0.00003'), decimal.Decimal('0.18'))

    def sawtooth_ticks(self, count=60):
        """Ticks one second apart whose bid goes 177.00, 176.80, 177.00, 176.80 and so on, with the ask 0.20 above.

        Args:
            count (int): How many ticks.

        Returns:
            list: Tuples of time, bid and ask.
        """
        ticks = []
        for index in range(count):
            if index % 2 == 0:
                bid = decimal.Decimal('177.00')
            else:
                bid = decimal.Decimal('176.80')
            ticks.append((START + datetime.timedelta(seconds=index), bid, bid + decimal.Decimal('0.20')))
        return ticks

    def run(self):
        """Runs every check and prints how many passed.

        Returns:
            int: 0 when every check passed, 1 when any failed.
        """
        self.flicker_of_a_falling_bid()
        self.flicker_of_a_rising_ask()
        self.flicker_needs_thirty_moves()
        self.flicker_reads_the_side_it_watches()
        self.flicker_refuses_a_bad_side_or_horizon()
        self.switch_on_from_the_flicker()
        self.switch_on_from_the_spread()
        self.switch_on_refuses_nothing_to_go_on()
        self.levels_of_a_bought_option()
        self.levels_without_measured_figures()
        self.levels_without_a_quote_or_history()
        self.levels_for_an_unknown_segment_or_broker()
        self.levels_read_the_tables_once_a_day()

        total = self.passed + len(self.failed)
        print(f'{total - len(self.failed)}/{total} checks passed.')
        if self.failed:
            return 1
        return 0

    def flicker_of_a_falling_bid(self):
        """A bid that drops 0.20 every other second has moves of 0.20 from the high ticks and 0 from the low ones, so the 90th percentile is 0.20 and the 40th is 0.

        Returns:
            None: This method returns nothing.
        """
        samples = []
        for moment, bid, ask in self.sawtooth_ticks():
            del ask
            samples.append((moment, bid))
        flicker = PriceFlicker('BUY', 5, samples)
        moves = flicker.moves()
        self.check('falling: moves measured', len(moves), 59)
        self.check('falling: 90th', flicker.distance(), decimal.Decimal('0.20'))
        self.check('falling: 40th', flicker.distance(40), decimal.Decimal('0'))

    def flicker_of_a_rising_ask(self):
        """A sold position watches the ask: one that rises 0.30 two seconds after each tick has a flicker of 0.30.

        Returns:
            None: This method returns nothing.
        """
        samples = []
        for index in range(40):
            if index % 3 == 2:
                price = decimal.Decimal('100.30')
            else:
                price = decimal.Decimal('100.00')
            samples.append((START + datetime.timedelta(seconds=index), price))
        flicker = PriceFlicker('SELL', 2, samples)
        self.check('rising: 90th', flicker.distance(), decimal.Decimal('0.30'))

    def flicker_needs_thirty_moves(self):
        """Thirty ticks give 29 moves, too few for a flicker; and a tick with nothing after it within the horizon has no move.

        Returns:
            None: This method returns nothing.
        """
        samples = []
        for moment, bid, ask in self.sawtooth_ticks(30):
            del ask
            samples.append((moment, bid))
        self.check('too few', PriceFlicker('BUY', 5, samples).distance(), None)
        lonely = [(START, decimal.Decimal(1)), (START + datetime.timedelta(seconds=10), decimal.Decimal(1))]
        self.check('nothing within the horizon', PriceFlicker('BUY', 5, lonely).moves(), [])

    def flicker_reads_the_side_it_watches(self):
        """`read` takes the bid for a bought position and the ask for a sold one.

        Returns:
            None: This method returns nothing.
        """
        database = StandInTickDatabase(self.sawtooth_ticks(3))
        bought = PriceFlicker('BUY')
        bought.read(database.connect, OPTION, START)
        sold = PriceFlicker('SELL')
        sold.read(database.connect, OPTION, START)
        self.check('read: bid', bought.samples[1][1], decimal.Decimal('176.80'))
        self.check('read: ask', sold.samples[1][1], decimal.Decimal('177.00'))

    def flicker_refuses_a_bad_side_or_horizon(self):
        """An opening side other than BUY or SELL, or a horizon of zero, raises ValueError.

        Returns:
            None: This method returns nothing.
        """
        for opening_side, horizon in (('LONG', 5), ('BUY', 0)):
            try:
                PriceFlicker(opening_side, horizon)
            except ValueError:
                self.check(f'flicker refused: {opening_side} {horizon}', True, True)
                continue
            self.check(f'flicker refused: {opening_side} {horizon}', False, True)

    def tripwire(self, opening_side):
        """The tripwire of 65 option units opened at 177.00 with a slip allowance of 58.03 basis points: 178.50 bought, 175.50 sold.

        Args:
            opening_side (str): `BUY` or `SELL`.

        Returns:
            TripwirePrice: The tripwire.
        """
        breakeven = BreakevenPrice(self.option_rate(), opening_side, '177', 65, 0, '0.05')
        return TripwirePrice(breakeven, decimal.Decimal('0.005803'))

    def switch_on_from_the_flicker(self):
        """A flicker of 0.80 puts the switch-on at 179.30 bought and 174.70 sold, 2.30 from the entry; 0.83 rounds away to 179.35.

        Returns:
            None: This method returns nothing.
        """
        bought = SwitchOnPrice(self.tripwire('BUY'), decimal.Decimal('0.80'))
        sold = SwitchOnPrice(self.tripwire('SELL'), decimal.Decimal('0.80'))
        self.check('flicker: bought', (bought.price(), bought.distance_from_entry(), bought.source()), (decimal.Decimal('179.30'), decimal.Decimal('2.30'), 'measured'))
        self.check('flicker: sold', (sold.price(), sold.distance_from_entry()), (decimal.Decimal('174.70'), decimal.Decimal('2.30')))
        self.check('flicker: rounded away', SwitchOnPrice(self.tripwire('BUY'), decimal.Decimal('0.83')).price(), decimal.Decimal('179.35'))

    def switch_on_from_the_spread(self):
        """With no flicker, a spread of 0.20 and two ticks put the switch-on 0.30 beyond the tripwire.

        Returns:
            None: This method returns nothing.
        """
        switch_on = SwitchOnPrice(self.tripwire('BUY'), spread='0.20')
        self.check('spread: price', (switch_on.price(), switch_on.source(), switch_on.distance_from_tripwire()), (decimal.Decimal('178.80'), 'spread', decimal.Decimal('0.30')))
        untidy = SwitchOnPrice(TripwirePrice(BreakevenPrice(self.option_rate(), 'BUY', '177', 65), decimal.Decimal('0.005803')), decimal.Decimal('0.8'))
        self.check('no tick size', untidy.price(), untidy.tripwire.price() + decimal.Decimal('0.8'))

    def switch_on_refuses_nothing_to_go_on(self):
        """No flicker and no spread, or a flicker below zero, raises ValueError.

        Returns:
            None: This method returns nothing.
        """
        for flicker, spread in ((None, None), (decimal.Decimal('-0.1'), None)):
            try:
                SwitchOnPrice(self.tripwire('BUY'), flicker, spread)
            except ValueError:
                self.check(f'switch-on refused: {flicker} {spread}', True, True)
                continue
            self.check(f'switch-on refused: {flicker} {spread}', False, True)

    def service(self, ticks=None, slips=None):
        """A levels service over in-memory tables and a stand-in database.

        Args:
            ticks (list | None): The tick rows the database answers.
            slips (list | None): The slip rows it answers.

        Returns:
            tuple: The `BreakevenLevels` and the `StandInTickDatabase`.
        """
        database = StandInTickDatabase(ticks, slips)
        charges = LoadedChargeRateTable(self.logger, [self.option_rate()])
        fees = {
            'delivery': decimal.Decimal(0),
            'fno': decimal.Decimal(0),
            'intraday': decimal.Decimal(0),
        }
        dear = {
            'delivery': decimal.Decimal(0),
            'fno': decimal.Decimal(20),
            'intraday': decimal.Decimal(20),
        }
        costs = LoadedBrokerCostTable(self.logger, {
            'zerodha': BrokerCosts('zerodha', 9, 375, None, 4500, dear),
            'wisdom_capital': BrokerCosts('wisdom_capital', 8, 540, None, None, fees),
            'flattrade': BrokerCosts('flattrade', 10, 180, None, None, fees),
        })
        return BreakevenLevels(charges, costs, StopSlipAllowance(), database.connect), database

    def details(self):
        """The option's details as `/details` answers them.

        Returns:
            dict: The details.
        """
        return {
            'instrument_id': OPTION,
            'segment': SEGMENT,
            'shape': 'option',
            'tick_size': '0.05',
        }

    def quote(self):
        """A quote with a best bid of 177.00 and a best ask of 177.20.

        Returns:
            dict: The quote document's depth.
        """
        return {'depth': {'buy': [{'price': 177.0}], 'sell': [{'price': 177.2}]}}

    def levels_of_a_bought_option(self):
        """With 40 measured slips of 58 basis points and a sawtooth flicker of 0.20, a call bought at 177.00 at the cheapest broker has a floor of 177.45, a tripwire of 178.50 and a switch-on of 178.70.

        Returns:
            None: This method returns nothing.
        """
        slips = []
        for index in range(40):
            slips.append((SEGMENT, 'SELL', decimal.Decimal('58')))
        service, database = self.service(self.sawtooth_ticks(), slips)
        del database
        answer = service.levels(self.details(), self.quote(), decimal.Decimal('177'), 65, now=START)
        self.check('levels: broker', (answer['broker'], answer['brokerage_per_order'], answer['category']), ('flattrade', '0', 'fno'))
        self.check('levels: floor', (answer['floor']['price'], answer['floor']['distance_from_entry']), ('177.45', '0.45'))
        self.check('levels: tripwire', (answer['tripwire']['price'], answer['tripwire']['source'], answer['tripwire']['stops_measured']), ('178.50', 'measured', 40))
        self.check('levels: switch-on', (answer['switch_on']['price'], answer['switch_on']['source'], answer['switch_on']['flicker']), ('178.70', 'measured', '0.20'))
        self.check('levels: spread', answer['spread'], '0.2')
        named = service.levels(self.details(), self.quote(), decimal.Decimal('177'), 65, broker='zerodha', now=START)
        self.check('levels: named broker', (named['brokerage_per_order'], named['floor']['price']), ('20', '178.15'))

    def levels_without_measured_figures(self):
        """With no measured slips or flicker, both levels fall back to the spread: tripwire 177.75 and switch-on 178.05.

        Returns:
            None: This method returns nothing.
        """
        service, database = self.service()
        del database
        answer = service.levels(self.details(), self.quote(), decimal.Decimal('177'), 65, now=START)
        self.check('fallback: tripwire', (answer['tripwire']['price'], answer['tripwire']['source'], answer['tripwire']['slip_basis_points']), ('177.75', 'spread', None))
        self.check('fallback: switch-on', (answer['switch_on']['price'], answer['switch_on']['source'], answer['switch_on']['ticks_measured']), ('178.05', 'spread', 0))

    def levels_without_a_quote_or_history(self):
        """With no quote and no measured figures, only the floor is known.

        Returns:
            None: This method returns nothing.
        """
        service, database = self.service()
        del database
        answer = service.levels(self.details(), None, decimal.Decimal('177'), 65, now=START)
        self.check('floor only', (answer['floor']['price'], answer['tripwire'], answer['switch_on'], answer['spread']), ('177.45', None, None, None))
        self.check('empty book', service.spread({'depth': {'buy': [], 'sell': [{'price': 1}]}}), None)

    def levels_for_an_unknown_segment_or_broker(self):
        """A segment with no charge row, or a broker with no cost row, raises BreakevenLevelsError with status 409.

        Returns:
            None: This method returns nothing.
        """
        service, database = self.service()
        del database
        details = dict(self.details())
        details['segment'] = 'mcx_commodity_futures'
        details['shape'] = 'future'
        for name, these_details, broker in (('segment', details, None), ('broker', self.details(), 'nobody')):
            try:
                service.levels(these_details, self.quote(), decimal.Decimal('177'), 65, broker=broker, now=START)
            except BreakevenLevelsError as error:
                self.check(f'unknown {name}', (error.status, 'unified.' in error.message), (409, True))
                continue
            self.check(f'unknown {name}', False, True)

    def levels_read_the_tables_once_a_day(self):
        """`refresh` reads the tables on the first request of a day in India and not again that day.

        Returns:
            None: This method returns nothing.
        """
        service, database = self.service()
        del database
        self.check('first read', service.refresh(START), True)
        self.check('same day', service.refresh(START + datetime.timedelta(hours=3)), False)
        self.check('next day', service.refresh(START + datetime.timedelta(days=1)), True)
        self.check('cheapest without rows', BreakevenLevels(None, LoadedBrokerCostTable(self.logger), None, None).cheapest_broker('fno'), None)


if __name__ == '__main__':
    sys.exit(BreakevenLevelsSuite().run())
