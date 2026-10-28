"""Offline checks of the trade charges and the real breakeven: the charge rate table, one day's charges against Flattrade's bill, and the breakeven price of bought and sold positions.

The bill is Flattrade's for 19 October 2026 (FO20261019), 178 round trips in NIFTY 27 October 2026 options worth 20,49,940.75 bought and 20,48,683.00 sold. The breakeven figures were worked out by hand and with plain floating point outside the code under test. No PostgreSQL, Redis, credentials or network are used.

Typical usage:

    python -m test_runs.trade_charges
"""

import decimal
import logging
import sys

from unified_broker_interface.utilities.execution_costs.breakeven_price import (
    BreakevenPrice,
)
from unified_broker_interface.utilities.execution_costs.charge_rate_table import (
    ChargeRate,
    ChargeRateTable,
)
from unified_broker_interface.utilities.execution_costs.trade_charges import (
    TradeCharges,
)

BILL = {
    'stt': decimal.Decimal('3073.00'),
    'exchange_charge': decimal.Decimal('1456.24'),
    'gst': decimal.Decimal('262.86'),
    'stamp_duty': decimal.Decimal('61.00'),
    'sebi_fee': decimal.Decimal('4.10'),
    'total': decimal.Decimal('4857.20'),
}


class TradeChargesSuite:
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
        self.logger = logging.getLogger('test_runs.trade_charges')
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
        """The NSE index option row, as seeded and as checked against the bill.

        Returns:
            ChargeRate: The row.
        """
        return ChargeRate(
            'nse_equity_index_options',
            'fno',
            decimal.Decimal('0'),
            decimal.Decimal('0.0015'),
            decimal.Decimal('0.0003553'),
            decimal.Decimal('0.000001'),
            decimal.Decimal('0.00003'),
            decimal.Decimal('0.18'),
        )

    def equity_rate(self, category):
        """An NSE equity row, as seeded.

        Args:
            category (str): `delivery` or `intraday`.

        Returns:
            ChargeRate: The row.
        """
        if category == 'delivery':
            stt_buy_rate = decimal.Decimal('0.001')
            stt_sell_rate = decimal.Decimal('0.001')
            stamp_buy_rate = decimal.Decimal('0.00015')
        else:
            stt_buy_rate = decimal.Decimal('0')
            stt_sell_rate = decimal.Decimal('0.00025')
            stamp_buy_rate = decimal.Decimal('0.00003')
        return ChargeRate(
            'nse_equities',
            category,
            stt_buy_rate,
            stt_sell_rate,
            decimal.Decimal('0.0000307'),
            decimal.Decimal('0.000001'),
            stamp_buy_rate,
            decimal.Decimal('0.18'),
        )

    def run(self):
        """Runs every check and prints how many passed.

        Returns:
            int: 0 when every check passed, 1 when any failed.
        """
        self.the_category_follows_the_brokerage_rule()
        self.a_segment_without_a_row_has_no_rate()
        self.the_side_rates_add_gst_where_it_applies()
        self.one_days_charges_match_the_bill()
        self.brokerage_carries_gst()
        self.a_bought_option_at_a_free_broker()
        self.a_sold_option_at_a_free_broker()
        self.brokerage_moves_the_breakeven_away()
        self.a_small_equity_trade_with_brokerage()
        self.an_exit_at_the_breakeven_never_loses()
        self.a_bad_side_or_quantity_is_refused()

        total = self.passed + len(self.failed)
        print(f'{total - len(self.failed)}/{total} checks passed.')
        if self.failed:
            return 1
        return 0

    def the_category_follows_the_brokerage_rule(self):
        """A derivative is `fno` with any product, a `CNC` share is `delivery`, and any other share is `intraday`.

        Returns:
            None: This method returns nothing.
        """
        table = ChargeRateTable(self.logger)
        self.check('category: option', table.category('derivative', 'NRML'), 'fno')
        self.check('category: option bought CNC', table.category('derivative', 'CNC'), 'fno')
        self.check('category: delivery', table.category('security', 'CNC'), 'delivery')
        self.check('category: intraday', table.category('security', 'MIS'), 'intraday')

    def a_segment_without_a_row_has_no_rate(self):
        """The table answers a row it holds and None for one it does not, and is empty until rows are given.

        Returns:
            None: This method returns nothing.
        """
        self.check('empty table', ChargeRateTable(self.logger).is_loaded(), False)
        table = ChargeRateTable(self.logger, [self.option_rate()])
        self.check('loaded', table.is_loaded(), True)
        self.check('row found', table.rate('nse_equity_index_options', 'fno').stt_sell_rate, decimal.Decimal('0.0015'))
        self.check('no row', table.rate('mcx_commodity_futures', 'fno'), None)

    def the_side_rates_add_gst_where_it_applies(self):
        """Each side's rate is its own taxes plus the exchange charge and SEBI fee with 18% GST on them.

        Returns:
            None: This method returns nothing.
        """
        rate = self.option_rate()
        self.check('buy side', rate.buy_side_rate(), decimal.Decimal('0.000450434'))
        self.check('sell side', rate.sell_side_rate(), decimal.Decimal('0.001920434'))

    def one_days_charges_match_the_bill(self):
        """The 19 October fills give each line of Flattrade's bill, and the total within one rupee of it.

        STT and stamp duty differ only by the bill's rounding to the rupee.

        Returns:
            None: This method returns nothing.
        """
        charges = TradeCharges(
            self.option_rate(),
            decimal.Decimal('2049940.75'),
            decimal.Decimal('2048683.00'),
        )
        parts = charges.parts()
        self.check('bill: exchange charge', parts['exchange_charge'], BILL['exchange_charge'])
        self.check('bill: SEBI fee', parts['sebi_fee'], BILL['sebi_fee'])
        self.check('bill: GST', parts['gst'], BILL['gst'])
        self.check('bill: STT', parts['stt'], decimal.Decimal('3073.02'))
        self.check('bill: stamp duty', parts['stamp_duty'], decimal.Decimal('61.50'))
        self.check('bill: total', parts['total'], decimal.Decimal('4857.72'))
        self.check('bill: total within a rupee', abs(parts['total'] - BILL['total']) < 1, True)
        self.check('bill: net', charges.net_profit().quantize(decimal.Decimal('0.01')), decimal.Decimal('-6115.47'))

    def brokerage_carries_gst(self):
        """Forty rupees of brokerage adds itself and 7.20 of GST.

        Returns:
            None: This method returns nothing.
        """
        without = TradeCharges(self.option_rate(), 11505, 11505)
        with_brokerage = TradeCharges(self.option_rate(), 11505, 11505, 40)
        difference = with_brokerage.total() - without.total()
        self.check('brokerage and its GST', difference, decimal.Decimal('47.20'))

    def a_bought_option_at_a_free_broker(self):
        """65 units bought at 177 break even at 177.4205, which rounds up to 177.45.

        Returns:
            None: This method returns nothing.
        """
        breakeven = BreakevenPrice(self.option_rate(), 'BUY', '177', 65, tick_size='0.05')
        self.check('bought: exact', breakeven.exact_price(), decimal.Decimal('177.4205'))
        self.check('bought: price', breakeven.price(), decimal.Decimal('177.45'))
        self.check('bought: distance', breakeven.distance(), decimal.Decimal('0.45'))

    def a_sold_option_at_a_free_broker(self):
        """65 units sold at 177 break even when bought back at 176.5805, which rounds down to 176.55.

        Returns:
            None: This method returns nothing.
        """
        breakeven = BreakevenPrice(self.option_rate(), 'SELL', '177', 65, tick_size='0.05')
        self.check('sold: exact', breakeven.exact_price(), decimal.Decimal('176.5805'))
        self.check('sold: price', breakeven.price(), decimal.Decimal('176.55'))
        self.check('sold: distance', breakeven.distance(), decimal.Decimal('0.45'))

    def brokerage_moves_the_breakeven_away(self):
        """Twenty rupees an order, as at Zerodha, moves the same option's breakeven to 178.15 bought and 175.85 sold.

        Returns:
            None: This method returns nothing.
        """
        bought = BreakevenPrice(self.option_rate(), 'BUY', '177', 65, 20, '0.05')
        sold = BreakevenPrice(self.option_rate(), 'SELL', '177', 65, 20, '0.05')
        self.check('brokerage: bought', (bought.exact_price(), bought.price()), (decimal.Decimal('178.1481'), decimal.Decimal('178.15')))
        self.check('brokerage: sold', (sold.exact_price(), sold.price()), (decimal.Decimal('175.8547'), decimal.Decimal('175.85')))

    def a_small_equity_trade_with_brokerage(self):
        """One share bought intraday at 500 with twenty rupees an order must be sold at 547.40, while ten delivery shares at 1,500 with no brokerage need 1,503.35.

        Returns:
            None: This method returns nothing.
        """
        intraday = BreakevenPrice(self.equity_rate('intraday'), 'BUY', '500', 1, 20, '0.05')
        delivery = BreakevenPrice(self.equity_rate('delivery'), 'BUY', '1500', 10, 0, '0.05')
        self.check('intraday: one share', (intraday.exact_price(), intraday.price()), (decimal.Decimal('547.3911'), decimal.Decimal('547.40')))
        self.check('delivery: ten shares', (delivery.exact_price(), delivery.price()), (decimal.Decimal('1503.3407'), decimal.Decimal('1503.35')))

    def an_exit_at_the_breakeven_never_loses(self):
        """For both sides and both brokerages, an exit at the breakeven nets zero or more and one tick worse nets less than zero.

        Returns:
            None: This method returns nothing.
        """
        tick = decimal.Decimal('0.05')
        for brokerage in (0, 20):
            for opening_side in ('BUY', 'SELL'):
                breakeven = BreakevenPrice(self.option_rate(), opening_side, '177', 65, brokerage, tick)
                at_breakeven = self.round_trip_profit(opening_side, breakeven.price(), brokerage)
                if opening_side == 'BUY':
                    worse = breakeven.price() - tick
                else:
                    worse = breakeven.price() + tick
                one_tick_worse = self.round_trip_profit(opening_side, worse, brokerage)
                name = f'never loses: {opening_side} with brokerage {brokerage}'
                self.check(name, (at_breakeven >= 0, one_tick_worse < 0), (True, True))

    def round_trip_profit(self, opening_side, exit_price, brokerage):
        """What 65 units opened at 177 make after every charge when closed at a price.

        Args:
            opening_side (str): `BUY` or `SELL`.
            exit_price (decimal.Decimal): The closing price.
            brokerage (int): The brokerage for one order.

        Returns:
            decimal.Decimal: The net profit in rupees.
        """
        entry_value = decimal.Decimal('177') * 65
        exit_value = exit_price * 65
        if opening_side == 'BUY':
            charges = TradeCharges(self.option_rate(), entry_value, exit_value, 2 * brokerage)
        else:
            charges = TradeCharges(self.option_rate(), exit_value, entry_value, 2 * brokerage)
        return charges.net_profit()

    def a_bad_side_or_quantity_is_refused(self):
        """An opening side other than BUY or SELL, or a quantity of zero, raises ValueError.

        Returns:
            None: This method returns nothing.
        """
        for opening_side, quantity in (('LONG', 65), ('BUY', 0)):
            try:
                BreakevenPrice(self.option_rate(), opening_side, '177', quantity)
            except ValueError:
                self.check(f'refused: {opening_side} {quantity}', True, True)
                continue
            self.check(f'refused: {opening_side} {quantity}', False, True)


if __name__ == '__main__':
    sys.exit(TradeChargesSuite().run())
