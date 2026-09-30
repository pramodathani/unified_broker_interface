"""Normalizes one INDmoney tick for a NIFTY future, whose quantities are already in units.

INDmoney reports derivative quantities in units rather than lots, so every multiplier is 1, and a future carries open interest. Its `close` is never the previous session's close, so `reported_close` is None both before and after the session ends.

The plan that `normalize` applies is normally compiled by `TickResolver` from the mapping cache. This program builds it by hand with the same rules, asking the normalizer how it reports each quantity field and when its close may be trusted, so it needs no database. The tick is shaped like the ones the broker's market feed publishes, with fixed times, so the output is the same on every run. The program normalizes the tick twice, once as received before the session's close and once as received after it, which only changes whether `reported_close` is kept. Order book levels are printed as (price, quantity, orders).

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/indmoney/IndmoneyTickNormalizer/example_2_a_future_in_units.py
"""

import datetime
import zoneinfo

from stock_brokers.instruments.ticks import base
from stock_brokers.instruments.ticks.base import (
    InstrumentPlan,
)
from stock_brokers.instruments.ticks.indmoney import (
    IndmoneyTickNormalizer,
)
from stock_brokers.instruments.ticks.utilities import sessions

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class NiftyFutureTickExample:
    """Normalizes one INDmoney tick through a hand-built plan and prints the result.

    Attributes:
        normalizer (IndmoneyTickNormalizer): The normalizer being shown.
        received_at (float): When the tick was received, in epoch seconds.
        tick (dict): The tick as the market feed published it.
        plan (InstrumentPlan): The plan for the tick's instrument.
    """

    def __init__(self):
        """Builds the normalizer, the tick and its plan.

        Returns:
            None: This method returns nothing.
        """
        self.normalizer = IndmoneyTickNormalizer()
        received = datetime.datetime(2026, 9, 15, 11, 5, tzinfo=INDIA)
        self.received_at = received.timestamp()
        self.tick = {
            'instrument_token': 'NFO:35003',
            'last_price': 25110.5,
            'last_quantity': 75,
            'average_price': 25096.2,
            'volume': 4533075,
            'buy_quantity': 312450,
            'sell_quantity': 298275,
            'ohlc': {
                'open': 25060.0,
                'high': 25134.9,
                'low': 25041.0,
                'close': 25080.0,
            },
            'oi': 14622300,
            'oi_day_high': 14801250,
            'oi_day_low': 14510025,
            'last_trade_time': self.received_at - 2.0,
            'exchange_timestamp': self.received_at - 1.0,
            'received_at': self.received_at,
            'depth': {
                'buy': [
                    {
                        'price': 25110.0,
                        'quantity': 225,
                        'orders': 3,
                    },
                    {
                        'price': 25109.5,
                        'quantity': 450,
                        'orders': 5,
                    },
                ],
                'sell': [
                    {
                        'price': 25110.5,
                        'quantity': 150,
                        'orders': 2,
                    },
                    {
                        'price': 25111.0,
                        'quantity': 375,
                        'orders': 4,
                    },
                ],
            },
        }
        self.plan = self.build_plan()

    def build_plan(self):
        """Compiles the plan for the tick's instrument the way the resolver would.

        Returns:
            InstrumentPlan: The plan.
        """
        exchange = 'nse'
        segment = 'nse_equity_index_futures'
        lot_size = 75
        broker_lot_size = 75
        multipliers = {}
        for field in base.QUANTITY_FIELDS:
            basis = self.normalizer.quantity_basis(exchange, field)
            if basis == base.BASIS_LOTS:
                multipliers[field] = lot_size
            elif basis == base.BASIS_BROKER_LOTS:
                multipliers[field] = lot_size // broker_lot_size
            else:
                multipliers[field] = 1
        identity = {
            'exchange': 'nse',
            'segment': 'nse_equity_index_futures',
            'shape': 'future',
            'symbol': 'NIFTY26SEPFUT',
            'underlying_symbol': 'NIFTY',
            'expiry_date': '2026-09-29',
            'strike_price': None,
            'option_type': None,
        }
        instrument_id = '11111111-1111-5111-8111-000000000105'
        broker_token = '35003'
        return InstrumentPlan(
            instrument_id=instrument_id,
            broker=IndmoneyTickNormalizer.BROKER_NAME,
            broker_token=broker_token,
            exchange=exchange,
            segment=segment,
            shape=identity['shape'],
            session=sessions.session_for(segment),
            lot_size=lot_size,
            multipliers=multipliers,
            price_decimals=2,
            negative_prices=False,
            close_policy=self.normalizer.close_policy(exchange),
            has_open_interest=identity['shape'] != 'security',
            trusts_last_trade_time=IndmoneyTickNormalizer.TRUSTS_LAST_TRADE_TIME,
            trusts_exchange_time=IndmoneyTickNormalizer.TRUSTS_EXCHANGE_TIME,
            identity_json=base.identity_json(
                instrument_id,
                IndmoneyTickNormalizer.BROKER_NAME,
                broker_token,
                identity,
                lot_size,
            ),
        )

    def run(self):
        """Prints the feed key, the plan's rules and the normalized values.

        Returns:
            None: This method returns nothing.
        """
        token = self.tick['instrument_token']
        feed_key = self.normalizer.feed_key(token)
        print(f'Token {token!r}: broker_token={feed_key.broker_token!r} order_symbol={feed_key.order_symbol!r}')
        volume_basis = self.normalizer.quantity_basis(self.plan.exchange, 'volume')
        print(f'Volume on {self.plan.exchange} is reported in {volume_basis}, multiplier {self.plan.multipliers["volume"]}')
        print(f'Close policy on {self.plan.exchange}: {self.normalizer.close_policy(self.plan.exchange)}')
        before_close = self.normalizer.normalize(self.tick, self.plan, True)
        print('Normalized, received before the close:')
        for name, value in before_close.items():
            print(f'  {name}: {value}')
        after_close = self.normalizer.normalize(self.tick, self.plan, False)
        print(f'reported_close when received after the close: {after_close["reported_close"]}')


if __name__ == '__main__':
    NiftyFutureTickExample().run()
