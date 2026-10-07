"""Offline checks of the lowest-cost selector's funds check and the margin estimate behind it.

The estimate is checked against what the brokers' own margin calculators answered on 2026-09-30 at about 10:40 IST, for the same orders at the same prices, so a change that makes it less accurate or less cautious fails here. The funds check is run against a scripted funds document and a scripted reply from its Lua script, so no Redis, database, credentials or network are used.

Typical usage:

    python -m test_runs.funds_check
"""

import datetime
import decimal
import json
import logging
import sys

from unified_broker_interface.utilities.broker_selection.lowest_cost import (
    LowestCostSelector,
)
from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCosts,
    BrokerCostTable,
)
from unified_broker_interface.utilities.broker_selection.utilities.funds_check import (
    FundsCheck,
)
from unified_broker_interface.utilities.broker_selection.utilities.funds_reservations import (
    FundsReservations,
)
from unified_broker_interface.utilities.broker_selection.utilities.margin_estimate import (
    MarginEstimate,
)
from unified_broker_interface.utilities.broker_selection.utilities.margin_rate_table import (
    MarginRate,
    MarginRateTable,
)
from unified_broker_interface.utilities.broker_selection.utilities.option_payoff import (
    OptionPayoff,
)
from unified_broker_interface.utilities.broker_selection.utilities.order_legs import (
    OrderLegs,
)
from unified_broker_interface.utilities.broker_selection.utilities.priced_leg import (
    PricedLeg,
)

NIFTY_SPOT = decimal.Decimal('22721.25')
NOW = datetime.datetime(2026, 9, 30, 10, 40, 0)
READ_AT = '2026-09-30 10:39:59.500000'
POSITIONS_WRITTEN_AT = '2026-09-30T10:39:59'

IDENTITIES = {
    'INFY': {
        'segment': 'nse_equities',
        'shape': 'security',
        'underlying_symbol': None,
        'expiry_date': None,
        'strike_price': None,
        'option_type': None,
    },
    'NIFTYFUT': {
        'segment': 'nse_equity_index_futures',
        'shape': 'future',
        'underlying_symbol': 'NIFTY',
        'expiry_date': '2026-10-27',
        'strike_price': None,
        'option_type': None,
    },
    'CRUDEFUT': {
        'segment': 'mcx_commodity_futures',
        'shape': 'future',
        'underlying_symbol': 'CRUDEOIL',
        'expiry_date': '2026-10-19',
        'strike_price': None,
        'option_type': None,
    },
}

LAST_PRICES = {
    'INFY': decimal.Decimal('1017.7'),
    'NIFTYFUT': decimal.Decimal('22833.7'),
    'CRUDEFUT': decimal.Decimal('8618'),
    'NIFTY22800CE': decimal.Decimal('122.5'),
    'NIFTY23000CE': decimal.Decimal('51.6'),
    'NIFTY23200CE': decimal.Decimal('19.0'),
    'NIFTY22600PE': decimal.Decimal('82.0'),
    'NIFTY22400PE': decimal.Decimal('38.1'),
}

COST_ROWS = [
    ('dhan', '1.000', '1.000', '1.000', True),
    ('flattrade', '1.101', '1.111', '1.110', True),
    ('fyers', '1.005', '1.001', '1.000', False),
    ('stoxkart', None, None, None, None),
    ('zerodha', '1.000', '1.000', '1.000', True),
]


class StandInOrder:
    """An order carrying only what the margin estimate reads.

    Attributes:
        transaction_type (str): `BUY` or `SELL`.
        product (str): `CNC`, `MIS` or `NRML`.
        order_type (str): `LIMIT` or `MARKET`.
        quantity (int): The quantity in units.
        price (decimal.Decimal | None): The limit price, or None.
        trigger_price (decimal.Decimal | None): The trigger price, or None.
        dry_run (bool): Whether the order is a dry run.
    """

    def __init__(self, transaction_type, product, quantity, price=None, dry_run=False):
        """Builds the order.

        Args:
            transaction_type (str): `BUY` or `SELL`.
            product (str): The product.
            quantity (int): The quantity in units.
            price (decimal.Decimal | None): The limit price, or None for a market order.
            dry_run (bool): Whether the order is a dry run.

        Returns:
            None: This method returns nothing.
        """
        self.transaction_type = transaction_type
        self.product = product
        self.order_type = 'MARKET'
        if price is not None:
            self.order_type = 'LIMIT'
        self.quantity = quantity
        self.price = price
        self.trigger_price = None
        self.dry_run = dry_run


class RecordingPipeline:
    """A pipeline that only records the commands queued on it.

    Attributes:
        commands (list): Each queued command as a tuple whose first element is its name.
    """

    def __init__(self):
        """Builds an empty pipeline.

        Returns:
            None: This method returns nothing.
        """
        self.commands = []

    def get(self, key):
        """Records a `GET`.

        Args:
            key (str): The key.

        Returns:
            RecordingPipeline: This pipeline.
        """
        self.commands.append((
            'get',
            key,
        ))
        return self

    def eval(self, script, key_count, *keys_and_arguments):
        """Records an `EVAL`.

        Args:
            script (str): The Lua script.
            key_count (int): How many of the values are keys.
            *keys_and_arguments (str | int): The keys, then the arguments.

        Returns:
            RecordingPipeline: This pipeline.
        """
        del script
        self.commands.append((
            'eval',
            key_count,
            list(keys_and_arguments),
        ))
        return self


class FundsCheckSuite:
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
        self.logger = logging.getLogger('test_runs.funds_check')
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

    def check_near(self, name, actual, broker_answer, lowest_share, highest_share):
        """Checks that an estimate lies within a band around what a broker answered.

        Args:
            name (str): What is being checked.
            actual (decimal.Decimal | None): The estimate.
            broker_answer (str): What the broker's calculator answered.
            lowest_share (str): The lowest acceptable estimate, as a share of the answer.
            highest_share (str): The highest acceptable estimate, as a share of the answer.

        Returns:
            None: This method returns nothing.
        """
        answer = decimal.Decimal(broker_answer)
        low = answer * decimal.Decimal(lowest_share)
        high = answer * decimal.Decimal(highest_share)
        inside = actual is not None and low <= actual <= high
        self.check(f'{name} (estimate {actual}, broker {broker_answer})', inside, True)

    def margin_rate_table(self):
        """A margin rate table with the rows the DDL seeds for the segments checked here.

        Returns:
            MarginRateTable: The table.
        """
        rows = [
            MarginRate('nse_equities', '', decimal.Decimal('0.20'), decimal.Decimal('0')),
            MarginRate('nse_equity_index_futures', '', decimal.Decimal('0.12'), decimal.Decimal('0.03')),
            MarginRate('nse_equity_index_options', '', decimal.Decimal('0.12'), decimal.Decimal('0.03')),
            MarginRate('nse_equity_index_futures', 'NIFTY', decimal.Decimal('0.0926'), decimal.Decimal('0.02')),
            MarginRate('nse_equity_index_options', 'NIFTY', decimal.Decimal('0.0926'), decimal.Decimal('0.02')),
            MarginRate('mcx_commodity_futures', '', decimal.Decimal('0.45'), decimal.Decimal('0.02')),
            MarginRate('mcx_commodity_futures', 'CRUDEOIL', decimal.Decimal('0.302'), decimal.Decimal('0.0125')),
        ]
        return MarginRateTable(self.logger, rows)

    def cost_table(self):
        """A cost table with the measured margin columns for five brokers.

        Returns:
            BrokerCostTable: The table.
        """
        rows = {}
        for broker_name, intraday, fno, commodity, hedge in COST_ROWS:
            multipliers = {
                'intraday': self.decimal_or_none(intraday),
                'fno': self.decimal_or_none(fno),
                'commodity': self.decimal_or_none(commodity),
            }
            fees = {
                'delivery': decimal.Decimal(0),
                'fno': decimal.Decimal(20),
                'intraday': decimal.Decimal(20),
            }
            rows[broker_name] = BrokerCosts(broker_name, 10, None, None, None, fees, multipliers, hedge)
        return BrokerCostTable(self.logger, rows)

    @staticmethod
    def decimal_or_none(text):
        """A text as a decimal, or None.

        Args:
            text (str | None): The text.

        Returns:
            decimal.Decimal | None: The number.
        """
        if text is None:
            return None
        return decimal.Decimal(text)

    @staticmethod
    def option_identity(strike_price, option_type):
        """The identity of a NIFTY option expiring on 2026-10-06.

        Args:
            strike_price (int): The strike.
            option_type (str): `CE` or `PE`.

        Returns:
            dict: The identity.
        """
        return {
            'segment': 'nse_equity_index_options',
            'shape': 'option',
            'underlying_symbol': 'NIFTY',
            'expiry_date': '2026-10-06',
            'strike_price': f'{strike_price}.0',
            'option_type': option_type,
        }

    def identity(self, name):
        """The identity of one of the instruments used here.

        Args:
            name (str): `INFY`, `NIFTYFUT`, `CRUDEFUT` or a NIFTY option such as `NIFTY22800CE`.

        Returns:
            dict: The identity.
        """
        if name in IDENTITIES:
            return IDENTITIES[name]
        return self.option_identity(int(name[5:10]), name[10:])

    def leg(self, name, transaction_type, product, quantity, with_price=True):
        """One priced leg at the prices of 2026-09-30.

        Args:
            name (str): The instrument's short name.
            transaction_type (str): `BUY` or `SELL`.
            product (str): The product.
            quantity (int): The quantity in units.
            with_price (bool): Whether the order carries the last price as its limit price, rather than being a market order.

        Returns:
            PricedLeg: The leg.
        """
        price = None
        if with_price:
            price = LAST_PRICES[name]
        underlying_price = None
        if name.startswith('NIFTY'):
            underlying_price = NIFTY_SPOT
        order = StandInOrder(transaction_type, product, quantity, price)
        return PricedLeg(name, order, self.identity(name), LAST_PRICES[name], underlying_price)

    def iron_condor(self, buys_first):
        """The iron condor sent to every broker's calculator on 2026-09-30.

        Args:
            buys_first (bool): Whether the two bought legs are sent before the two sold ones.

        Returns:
            list: The four `PricedLeg` legs in send order.
        """
        buys = [
            self.leg('NIFTY23200CE', 'BUY', 'NRML', 65),
            self.leg('NIFTY22400PE', 'BUY', 'NRML', 65),
        ]
        sells = [
            self.leg('NIFTY23000CE', 'SELL', 'NRML', 65),
            self.leg('NIFTY22600PE', 'SELL', 'NRML', 65),
        ]
        if buys_first:
            return buys + sells
        return sells + buys

    def run(self):
        """Runs every check and prints how many passed.

        Returns:
            int: 0 when every check passed, 1 when any failed.
        """
        self.single_orders_match_the_brokers()
        self.a_market_order_is_priced_at_the_last_trade()
        self.an_iron_condor_matches_the_brokers_with_hedge_benefit()
        self.sending_the_sells_first_costs_more()
        self.a_naked_short_call_has_no_limit_to_its_loss()
        self.legs_on_different_expiries_get_no_hedge_benefit()
        self.an_underlying_row_overrides_the_segment_row()
        self.reservations_last_until_the_funds_catch_up()
        self.the_check_is_off_until_the_rates_are_loaded()
        self.a_broker_short_of_cash_is_passed_over()
        self.a_measured_surcharge_can_tip_a_broker_over()
        self.an_unmeasured_broker_gets_the_default_surcharge()
        self.old_or_missing_funds_pass_a_broker_over()
        self.a_commodity_order_reads_the_commodity_pool()
        self.hedge_benefit_is_given_only_where_the_broker_allows_it()
        self.a_chosen_broker_reserves_the_margin()
        self.a_dry_run_reserves_nothing()
        self.an_order_without_a_price_skips_the_check()
        self.the_selector_rides_on_the_same_pipeline()
        self.a_sell_that_closes_a_held_option_needs_no_margin()
        self.a_buy_that_closes_a_short_future_needs_no_margin()
        self.a_sell_larger_than_the_holding_is_priced_as_usual()
        self.another_product_does_not_close_the_position()
        self.old_or_untrusted_positions_close_nothing()

        total = self.passed + len(self.failed)
        print(f'{total - len(self.failed)}/{total} checks passed.')
        if self.failed:
            return 1
        return 0

    def single_orders_match_the_brokers(self):
        """Each single-order estimate is within a narrow band of the brokers' own answers, and never far below them.

        Returns:
            None: This method returns nothing.
        """
        estimate = MarginEstimate(self.margin_rate_table())
        self.check_near(
            'INFY delivery buy',
            estimate.leg_margin(self.leg('INFY', 'BUY', 'CNC', 1)),
            '1017.7',
            '1.00',
            '1.00',
        )
        self.check(
            'INFY delivery sell needs no cash',
            estimate.leg_margin(self.leg('INFY', 'SELL', 'CNC', 1)),
            decimal.Decimal(0),
        )
        self.check_near(
            'INFY intraday buy',
            estimate.leg_margin(self.leg('INFY', 'BUY', 'MIS', 1)),
            '203.54',
            '0.99',
            '1.01',
        )
        self.check_near(
            'NIFTY future sold',
            estimate.leg_margin(self.leg('NIFTYFUT', 'SELL', 'NRML', 65)),
            '167109.41',
            '0.99',
            '1.01',
        )
        self.check_near(
            'NIFTY 22800 call sold, estimated from the index',
            estimate.leg_margin(self.leg('NIFTY22800CE', 'SELL', 'NRML', 65)),
            '161608.525',
            '1.00',
            '1.05',
        )
        self.check_near(
            'NIFTY 22800 call bought',
            estimate.leg_margin(self.leg('NIFTY22800CE', 'BUY', 'NRML', 65)),
            '7962.5',
            '1.00',
            '1.00',
        )
        self.check_near(
            'crude oil future bought',
            estimate.leg_margin(self.leg('CRUDEFUT', 'BUY', 'NRML', 100)),
            '271072.5',
            '0.99',
            '1.01',
        )

    def a_market_order_is_priced_at_the_last_trade(self):
        """An order without a limit price is valued at the instrument's last traded price.

        Returns:
            None: This method returns nothing.
        """
        estimate = MarginEstimate(self.margin_rate_table())
        self.check(
            'market buy of INFY for delivery',
            estimate.leg_margin(self.leg('INFY', 'BUY', 'CNC', 10, with_price=False)),
            decimal.Decimal('10177.0'),
        )

    def an_iron_condor_matches_the_brokers_with_hedge_benefit(self):
        """With hedge benefit the condor costs its 200-point loss plus exposure plus premiums, about what Groww, Dhan and Shoonya charged.

        Returns:
            None: This method returns nothing.
        """
        estimate = MarginEstimate(self.margin_rate_table())
        legs = self.iron_condor(buys_first=True)
        hedged = estimate.required(legs, True)
        self.check(
            'the condor loses at most 200 points on 65 units',
            OptionPayoff(legs).maximum_loss(),
            decimal.Decimal('13000.0'),
        )
        self.check_near('iron condor, hedged, against Groww', hedged, '75614.55', '1.00', '1.01')
        self.check_near('iron condor, hedged, against Shoonya', hedged, '75406.56', '1.00', '1.01')
        standalone = estimate.required(legs, False)
        self.check(
            'without hedge benefit the condor costs more than four times as much',
            standalone > hedged * 4,
            True,
        )

    def sending_the_sells_first_costs_more(self):
        """The requirement is the highest point along the way, so sending the sold legs first needs far more cash.

        Returns:
            None: This method returns nothing.
        """
        estimate = MarginEstimate(self.margin_rate_table())
        buys_first = estimate.required(self.iron_condor(buys_first=True), True)
        sells_first = estimate.required(self.iron_condor(buys_first=False), True)
        self.check('sells first needs more than buys first', sells_first > buys_first * 3, True)

    def a_naked_short_call_has_no_limit_to_its_loss(self):
        """A sold call with no bought call above it can lose without limit, so the payoff has no maximum loss.

        Returns:
            None: This method returns nothing.
        """
        legs = [
            self.leg('NIFTY23000CE', 'SELL', 'NRML', 65),
            self.leg('NIFTY22400PE', 'BUY', 'NRML', 65),
        ]
        self.check('naked short call', OptionPayoff(legs).maximum_loss(), None)
        estimate = MarginEstimate(self.margin_rate_table())
        self.check(
            'with no limit to the loss, the legs are added up',
            estimate.required(legs, True),
            estimate.required(legs, False),
        )

    def legs_on_different_expiries_get_no_hedge_benefit(self):
        """A future on a later expiry is not hedged against an option, because their payoffs do not settle together.

        Returns:
            None: This method returns nothing.
        """
        estimate = MarginEstimate(self.margin_rate_table())
        legs = [
            self.leg('NIFTY22400PE', 'BUY', 'NRML', 65),
            self.leg('NIFTYFUT', 'BUY', 'NRML', 65),
        ]
        self.check('different expiries cannot be hedged', estimate.can_be_hedged(legs), False)

    def an_underlying_row_overrides_the_segment_row(self):
        """A row naming an underlying wins over the segment's own row, which covers every other underlying.

        Returns:
            None: This method returns nothing.
        """
        table = self.margin_rate_table()
        self.check(
            'NIFTY has its own rate',
            table.rate('nse_equity_index_futures', 'NIFTY').total_rate(),
            decimal.Decimal('0.1126'),
        )
        self.check(
            'BANKNIFTY falls back to the segment',
            table.rate('nse_equity_index_futures', 'BANKNIFTY').total_rate(),
            decimal.Decimal('0.15'),
        )
        self.check('an unknown segment has no rate', table.rate('nse_mutual_funds', None), None)

    def reservations_last_until_the_funds_catch_up(self):
        """A reservation counts until the broker's funds were read more than the settle time after it.

        Returns:
            None: This method returns nothing.
        """
        reservations = FundsReservations(2)
        reserved_at = datetime.datetime(2026, 9, 30, 10, 40, 0)
        reservations.reserve('zerodha', decimal.Decimal('1000'), reserved_at)
        self.check(
            'read one second later, the funds do not show it yet',
            reservations.reserved('zerodha', reserved_at + datetime.timedelta(seconds=1)),
            decimal.Decimal('1000'),
        )
        self.check(
            'read three seconds later, the funds show it',
            reservations.reserved('zerodha', reserved_at + datetime.timedelta(seconds=3)),
            decimal.Decimal('0'),
        )

    def funds_document(self, overrides=None):
        """A unified funds document in which every broker has been read half a second ago.

        Args:
            overrides (dict | None): Fields to replace in a broker's entry, by broker name.

        Returns:
            str: The document as JSON.
        """
        entries = {
            'dhan': {'available_balance': 200000.0, 'pools': {}},
            'flattrade': {'available_balance': 180000.0, 'pools': {}},
            'fyers': {'available_balance': 100000.0, 'pools': {'equity': 100000.0, 'commodity': 0.0}},
            'stoxkart': {'available_balance': 180000.0, 'pools': {}},
            'zerodha': {'available_balance': 300000.0, 'pools': {'equity': 300000.0, 'commodity': 0.0}},
        }
        brokers = []
        for broker_name, fields in entries.items():
            entry = {
                'broker': broker_name,
                'status': 'ok',
                'as_of': READ_AT,
            }
            entry.update(fields)
            entry.update((overrides or {}).get(broker_name, {}))
            brokers.append(entry)
        return json.dumps({
            'brokers': brokers,
        })

    def script_reply(self, legs):
        """What the Lua script answers for these legs: identity, last price and underlying's last price for each.

        Args:
            legs (list): The `PricedLeg` legs.

        Returns:
            list: Three texts per leg.
        """
        reply = []
        for leg in legs:
            reply.append(json.dumps(leg.identity))
            reply.append(str(leg.last_price or ''))
            reply.append(str(leg.underlying_price or ''))
        return reply

    def funds_check(self, loaded=True):
        """A funds check with the measured multipliers, a 5% cushion and a 1.15 default.

        Args:
            loaded (bool): Whether the margin rate table has rows.

        Returns:
            FundsCheck: The check.
        """
        margin_rate_table = self.margin_rate_table()
        if not loaded:
            margin_rate_table = MarginRateTable(self.logger)
        return FundsCheck(self.cost_table(), margin_rate_table, True, 0.05, 1.15, 5, 2)

    def positions_document(self, positions, written_at=POSITIONS_WRITTEN_AT, statuses=None):
        """A unified positions document holding some net positions, with each broker's share.

        Args:
            positions (list): One `(instrument_id, product, by_broker)` tuple per position, where `by_broker` maps a broker name to its signed quantity.
            written_at (str): The document's `as_of`.
            statuses (dict | None): A status to give a broker other than `ok`, by broker name.

        Returns:
            str: The document as JSON.
        """
        net = []
        for instrument_id, product, by_broker in positions:
            quantity = 0
            for held in by_broker.values():
                quantity = quantity + held
            net.append({
                'instrument_id': instrument_id,
                'product': product,
                'quantity': quantity,
                'by_broker': by_broker,
            })
        brokers = []
        for broker_name in ['dhan', 'flattrade', 'fyers', 'stoxkart', 'zerodha']:
            brokers.append({
                'broker': broker_name,
                'status': (statuses or {}).get(broker_name, 'ok'),
            })
        return json.dumps({
            'net': net,
            'brokers': brokers,
            'as_of': written_at,
        })

    def decide(self, check, legs, funds_text=None, hedge_benefit=False, positions_text=None):
        """Queues and runs the check for some legs, as the selector does.

        Args:
            check (FundsCheck): The check.
            legs (list): The `PricedLeg` legs.
            funds_text (str | None): The funds document, or None for the default one.
            hedge_benefit (bool): Whether the caller asked for hedge benefit.
            positions_text (str | None): The positions document, or None for one holding nothing.

        Returns:
            dict: The reasons by broker name.
        """
        order_legs = OrderLegs(
            [(leg.instrument_id, leg.order) for leg in legs],
            hedge_benefit,
        )
        check.queue_redis_commands(RecordingPipeline(), legs[0].order, legs[0].instrument_id, order_legs)
        replies = [
            funds_text or self.funds_document(),
            self.script_reply(legs),
            positions_text or self.positions_document([]),
        ]
        return check.decide(replies, ['dhan', 'flattrade', 'fyers', 'stoxkart', 'zerodha'], NOW)

    def the_check_is_off_until_the_rates_are_loaded(self):
        """With an empty margin rate table nothing is queued and no broker is passed over.

        Returns:
            None: This method returns nothing.
        """
        check = self.funds_check(loaded=False)
        pipeline = RecordingPipeline()
        leg = self.leg('NIFTYFUT', 'SELL', 'NRML', 65)
        queued = check.queue_redis_commands(pipeline, leg.order, 'NIFTYFUT')
        self.check('nothing queued', (queued, pipeline.commands), (0, []))
        self.check('no reasons', check.decide([], ['zerodha'], NOW), {})

    def a_broker_short_of_cash_is_passed_over(self):
        """One NIFTY future sold needs about 175,500 with the cushion, which Fyers' 100,000 cannot cover, while Zerodha's 300,000 and Dhan's 200,000 can.

        Returns:
            None: This method returns nothing.
        """
        check = self.funds_check()
        reasons = self.decide(check, [self.leg('NIFTYFUT', 'SELL', 'NRML', 65)])
        self.check(
            'Fyers, and the two brokers with higher surcharges, are passed over',
            sorted(reasons),
            ['flattrade', 'fyers', 'stoxkart'],
        )
        self.check(
            'the reason gives both amounts',
            reasons['fyers'],
            'needs about 175,651.32 of margin but has 100,000.00 free',
        )
        self.check('Zerodha can afford it', check.reason('zerodha'), None)

    def a_measured_surcharge_can_tip_a_broker_over(self):
        """Flattrade's 11% surcharge takes the same future past its 180,000, which the exchange margin alone would fit in.

        Returns:
            None: This method returns nothing.
        """
        check = self.funds_check()
        reasons = self.decide(check, [self.leg('NIFTYFUT', 'SELL', 'NRML', 65)])
        self.check(
            'Flattrade is passed over for its surcharge',
            reasons.get('flattrade'),
            'needs about 194,953.67 of margin but has 180,000.00 free',
        )

    def an_unmeasured_broker_gets_the_default_surcharge(self):
        """Stoxkart has no margin calculator, so its estimate carries the 1.15 default and does not fit in 180,000.

        Returns:
            None: This method returns nothing.
        """
        check = self.funds_check()
        reasons = self.decide(check, [self.leg('NIFTYFUT', 'SELL', 'NRML', 65)])
        self.check(
            'Stoxkart is passed over',
            reasons.get('stoxkart'),
            'needs about 201,797.22 of margin but has 180,000.00 free',
        )

    def old_or_missing_funds_pass_a_broker_over(self):
        """A broker whose funds are stale, too old or missing is passed over, however small the order.

        Returns:
            None: This method returns nothing.
        """
        check = self.funds_check()
        overrides = {
            'dhan': {'status': 'stale'},
            'zerodha': {'as_of': '2026-09-30 10:39:50.000000'},
        }
        document = json.loads(self.funds_document(overrides))
        brokers = []
        for entry in document['brokers']:
            if entry['broker'] != 'stoxkart':
                brokers.append(entry)
        document['brokers'] = brokers
        reasons = self.decide(check, [self.leg('INFY', 'BUY', 'CNC', 1)], json.dumps(document))
        self.check('stale funds', reasons.get('dhan'), 'its funds are stale')
        self.check('old funds', reasons.get('zerodha'), 'its funds were read 10 seconds ago')
        self.check('missing funds', reasons.get('stoxkart'), 'has no funds in unified:portfolio:funds')
        self.check('fresh funds', reasons.get('fyers'), None)

    def a_commodity_order_reads_the_commodity_pool(self):
        """Zerodha and Fyers keep commodity money apart, and both have none there, so a crude oil future passes them over.

        Returns:
            None: This method returns nothing.
        """
        check = self.funds_check()
        reasons = self.decide(check, [self.leg('CRUDEFUT', 'BUY', 'NRML', 100)])
        self.check(
            'Zerodha has no commodity money',
            reasons.get('zerodha'),
            'needs about 284,587.91 of margin but has 0.00 free',
        )
        self.check('Fyers has no commodity money', 'fyers' in reasons, True)

    def hedge_benefit_is_given_only_where_the_broker_allows_it(self):
        """With hedge benefit asked for, the condor fits at Fyers only if Fyers gave the benefit, which it does not.

        Returns:
            None: This method returns nothing.
        """
        check = self.funds_check()
        reasons = self.decide(check, self.iron_condor(buys_first=True), hedge_benefit=True)
        self.check('Zerodha prices the condor hedged', reasons.get('zerodha'), None)
        self.check('Dhan prices the condor hedged', reasons.get('dhan'), None)
        self.check('Fyers prices every leg alone', 'fyers' in reasons, True)
        reasons = self.decide(check, self.iron_condor(buys_first=True), hedge_benefit=False)
        self.check('without the benefit Zerodha cannot afford it', 'zerodha' in reasons, True)

    def a_chosen_broker_reserves_the_margin(self):
        """After one future goes to Zerodha, a second one sees 300,000 less its reservation and cannot fit.

        Returns:
            None: This method returns nothing.
        """
        check = self.funds_check()
        self.decide(check, [self.leg('NIFTYFUT', 'SELL', 'NRML', 65)])
        check.reserve_chosen('zerodha')
        reasons = self.decide(check, [self.leg('NIFTYFUT', 'SELL', 'NRML', 65)])
        self.check(
            'the second future does not fit',
            reasons.get('zerodha'),
            'needs about 175,475.85 of margin but has 124,524.15 free',
        )

    def a_dry_run_reserves_nothing(self):
        """A dry run chooses a broker but sends nothing, so it must not hold that broker's cash.

        Returns:
            None: This method returns nothing.
        """
        check = self.funds_check()
        leg = self.leg('NIFTYFUT', 'SELL', 'NRML', 65)
        leg.order.dry_run = True
        self.decide(check, [leg])
        check.reserve_chosen('zerodha')
        self.check('nothing reserved', check.reservations.reserved('zerodha', None), decimal.Decimal(0))

    def an_order_without_a_price_skips_the_check(self):
        """A market order on an instrument with no quote cannot be valued, so no broker is passed over for funds.

        Returns:
            None: This method returns nothing.
        """
        check = self.funds_check()
        leg = PricedLeg('NIFTYFUT', StandInOrder('SELL', 'NRML', 65), IDENTITIES['NIFTYFUT'], None, None)
        self.check('no reasons', self.decide(check, [leg]), {})

    def the_selector_rides_on_the_same_pipeline(self):
        """The lowest-cost selector queues its counts and the check's three commands together, and answers for skipped brokers.

        Returns:
            None: This method returns nothing.
        """
        selector = LowestCostSelector(self.cost_table(), self.margin_rate_table())
        selector.funds_check = self.funds_check()
        pipeline = RecordingPipeline()
        leg = self.leg('NIFTYFUT', 'SELL', 'NRML', 65)
        queued = selector.queue_redis_commands(pipeline, leg.order, 'NIFTYFUT')
        names = []
        for command in pipeline.commands:
            names.append(command[0])
        self.check('four commands on one pipeline', (queued, names), (4, ['eval', 'get', 'eval', 'get']))
        count_reply = [0] * (4 * len(selector.cost_table.rows))
        replies = [
            count_reply,
            self.funds_document(),
            self.script_reply([leg]),
            self.positions_document([]),
        ]
        selector.funds_check.decide(replies[1:], ['fyers', 'zerodha'], NOW)
        self.check('Fyers is passed over', selector.passed_over_reason('fyers') is not None, True)
        self.check('Zerodha is not', selector.passed_over_reason('zerodha'), None)


    def short_of_cash(self):
        """A funds document in which no broker could afford to write a NIFTY option or sell a NIFTY future.

        Returns:
            str: The document as JSON.
        """
        overrides = {}
        for broker_name in ['dhan', 'flattrade', 'fyers', 'stoxkart', 'zerodha']:
            overrides[broker_name] = {
                'available_balance': 50000.0,
                'pools': {},
            }
        return self.funds_document(overrides)

    def a_sell_that_closes_a_held_option_needs_no_margin(self):
        """Selling 65 of a call Flattrade holds 65 of is an exit there, so Flattrade is offered it although nobody could afford to write the call; this is the exit refused on 2026-10-07.

        Returns:
            None: This method returns nothing.
        """
        check = self.funds_check()
        positions_text = self.positions_document([
            ('NIFTY22800CE', 'carry', {'flattrade': 65}),
        ])
        reasons = self.decide(
            check,
            [self.leg('NIFTY22800CE', 'SELL', 'NRML', 65)],
            self.short_of_cash(),
            positions_text=positions_text,
        )
        self.check(
            'only the brokers that do not hold the call are passed over',
            sorted(reasons),
            ['dhan', 'fyers', 'stoxkart', 'zerodha'],
        )
        self.check('Flattrade can take the exit', check.reason('flattrade'), None)
        check.reserve_chosen('flattrade')
        self.check(
            'an exit reserves no margin',
            check.reservations.reserved('flattrade', None),
            decimal.Decimal(0),
        )

    def a_buy_that_closes_a_short_future_needs_no_margin(self):
        """Buying back 65 of a future Zerodha is short 130 of closes half of it, so Zerodha is not passed over.

        Returns:
            None: This method returns nothing.
        """
        check = self.funds_check()
        positions_text = self.positions_document([
            ('NIFTYFUT', 'carry', {'zerodha': -130}),
        ])
        reasons = self.decide(
            check,
            [self.leg('NIFTYFUT', 'BUY', 'NRML', 65)],
            self.short_of_cash(),
            positions_text=positions_text,
        )
        self.check('Zerodha can take the buy back', 'zerodha' in reasons, False)
        self.check('Dhan holds nothing and is passed over', 'dhan' in reasons, True)

    def a_sell_larger_than_the_holding_is_priced_as_usual(self):
        """Selling 130 of a call Flattrade holds only 65 of would leave it short, and two sells of 65 cannot both count the same 65.

        Returns:
            None: This method returns nothing.
        """
        positions_text = self.positions_document([
            ('NIFTY22800CE', 'carry', {'flattrade': 65}),
        ])
        check = self.funds_check()
        reasons = self.decide(
            check,
            [self.leg('NIFTY22800CE', 'SELL', 'NRML', 130)],
            self.short_of_cash(),
            positions_text=positions_text,
        )
        self.check('one sell of 130 is priced', 'flattrade' in reasons, True)
        check = self.funds_check()
        reasons = self.decide(
            check,
            [
                self.leg('NIFTY22800CE', 'SELL', 'NRML', 65),
                self.leg('NIFTY22800CE', 'SELL', 'NRML', 65),
            ],
            self.short_of_cash(),
            positions_text=positions_text,
        )
        self.check('two sells of 65 are priced', 'flattrade' in reasons, True)

    def another_product_does_not_close_the_position(self):
        """An intraday sell of a call held as a carry position opens a new short at the broker, so it is priced.

        Returns:
            None: This method returns nothing.
        """
        check = self.funds_check()
        positions_text = self.positions_document([
            ('NIFTY22800CE', 'carry', {'flattrade': 65}),
        ])
        reasons = self.decide(
            check,
            [self.leg('NIFTY22800CE', 'SELL', 'MIS', 65)],
            self.short_of_cash(),
            positions_text=positions_text,
        )
        self.check('the intraday sell is priced', 'flattrade' in reasons, True)

    def old_or_untrusted_positions_close_nothing(self):
        """A positions document older than five seconds, or a broker whose positions are stale, is not trusted to show an exit.

        Returns:
            None: This method returns nothing.
        """
        held = [
            ('NIFTY22800CE', 'carry', {'flattrade': 65}),
        ]
        cases = [
            ('an old document', self.positions_document(held, '2026-09-30T10:39:50')),
            ('a document with no time', self.positions_document(held, '')),
            ('a broker whose positions are stale', self.positions_document(held, statuses={'flattrade': 'stale'})),
            ('an unreadable document', 'not json'),
        ]
        for name, positions_text in cases:
            check = self.funds_check()
            reasons = self.decide(
                check,
                [self.leg('NIFTY22800CE', 'SELL', 'NRML', 65)],
                self.short_of_cash(),
                positions_text=positions_text,
            )
            self.check(f'{name} is not trusted', 'flattrade' in reasons, True)

if __name__ == '__main__':
    sys.exit(FundsCheckSuite().run())
