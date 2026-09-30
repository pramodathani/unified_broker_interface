"""Builds the plan for one MCX crude oil future and applies it to a tick.

An `InstrumentPlan` holds every decision about one broker token that does not change from tick to tick: which instrument it is, the window its ticks are accepted in, the multiplier that turns each quantity into units, how many places prices are rounded to, and which of the broker's fields are trusted. The live service compiles one per token through `TickResolver`; this program fills one in by hand, so every attribute is visible, and then hands it to `ZerodhaTickNormalizer.normalize` to show what the plan is for.

The identity part of a unified quote is serialized once into the plan's `identity_json`, so the per-tick path only splices it in. The tick has a fixed receipt time, so the output is identical on every run. Nothing here needs Redis, a database or a broker.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/base/InstrumentPlan/example_1_a_plan_for_one_future.py
"""

import datetime
import zoneinfo

from stock_brokers.instruments.ticks import base
from stock_brokers.instruments.ticks.base import (
    InstrumentPlan,
)
from stock_brokers.instruments.ticks.utilities import sessions
from stock_brokers.instruments.ticks.zerodha import (
    ZerodhaTickNormalizer,
)

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class FuturePlanExample:
    """Builds a plan for a crude oil future, prints it and normalizes one tick with it.

    Attributes:
        plan (InstrumentPlan): The plan being shown.
        received_at (float): When the tick was received, in epoch seconds.
    """

    def __init__(self):
        """Builds the plan with a 100-barrel lot and quantities reported in lots.

        Returns:
            None: This method returns nothing.
        """
        identity = {
            'exchange': 'mcx',
            'segment': 'mcx_commodity_futures',
            'shape': 'future',
            'symbol': 'CRUDEOIL26OCTFUT',
            'underlying_symbol': 'CRUDEOIL',
            'expiry_date': datetime.date(2026, 10, 19),
            'strike_price': None,
            'option_type': None,
        }
        multipliers = {}
        for field in base.QUANTITY_FIELDS:
            multipliers[field] = 100
        self.plan = InstrumentPlan(
            instrument_id='11111111-1111-5111-8111-000000000101',
            broker='zerodha',
            broker_token='5720583',
            exchange='mcx',
            segment='mcx_commodity_futures',
            shape='future',
            session=sessions.session_for('mcx_commodity_futures'),
            lot_size=100,
            multipliers=multipliers,
            price_decimals=2,
            negative_prices=True,
            close_policy=base.CLOSE_ALWAYS,
            has_open_interest=True,
            trusts_last_trade_time=True,
            trusts_exchange_time=True,
            identity_json=base.identity_json(
                '11111111-1111-5111-8111-000000000101',
                'zerodha',
                '5720583',
                identity,
                100,
            ),
        )
        received = datetime.datetime(2026, 9, 15, 22, 46, tzinfo=INDIA)
        self.received_at = received.timestamp()

    def run(self):
        """Prints every attribute of the plan, then a tick normalized with it.

        Returns:
            None: This method returns nothing.
        """
        plan = self.plan
        print(f'instrument_id: {plan.instrument_id}')
        print(f'broker: {plan.broker}')
        print(f'broker_token: {plan.broker_token}')
        print(f'exchange: {plan.exchange}')
        print(f'segment: {plan.segment}')
        print(f'shape: {plan.shape}')
        print(f'session: {plan.session}')
        print(f'lot_size: {plan.lot_size}')
        print(f'multipliers: {plan.multipliers}')
        print(f'price_decimals: {plan.price_decimals}')
        print(f'negative_prices: {plan.negative_prices}')
        print(f'close_policy: {plan.close_policy}')
        print(f'has_open_interest: {plan.has_open_interest}')
        print(f'trusts_last_trade_time: {plan.trusts_last_trade_time}')
        print(f'trusts_exchange_time: {plan.trusts_exchange_time}')
        print(f'identity_json: {plan.identity_json}')
        tick = {
            'instrument_token': 5720583,
            'last_price': 9731.0,
            'last_quantity': 2,
            'volume': 67958,
            'ohlc': {
                'open': 9702.0,
                'high': 9745.0,
                'low': 9688.0,
                'close': 9722.0,
            },
            'oi': 18095,
            'received_at': self.received_at,
        }
        values = ZerodhaTickNormalizer().normalize(tick, self.plan, True)
        print('A tick normalized with this plan:')
        print(f"  last_price {values['last_price']}, last_quantity {values['last_quantity']}, volume {values['volume']}, oi {values['oi']}, reported_close {values['reported_close']}")


if __name__ == '__main__':
    FuturePlanExample().run()
