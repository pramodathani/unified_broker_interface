"""Normalizes one Groww tick for RELIANCE on NSE, whose last trade time and close are not trusted.

Groww's last trade time is not a true instant, so the normalizer leaves `last_trade_time` as None and keeps only the exchange time. Its `close` is never the previous session's close, so `reported_close` is None both before and after the session ends; the unified pipeline takes the previous close from elsewhere.

The plan that `normalize` applies is normally compiled by `TickResolver` from the mapping cache. This program builds it by hand with the same rules, asking the normalizer how it reports each quantity field and when its close may be trusted, so it needs no database. The tick is shaped like the ones the broker's market feed publishes, with fixed times, so the output is the same on every run. The program normalizes the tick twice, once as received before the session's close and once as received after it, which only changes whether `reported_close` is kept. Order book levels are printed as (price, quantity, orders).

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/groww/GrowwTickNormalizer/example_2_untrusted_time_and_close.py
"""

import datetime
import zoneinfo

from stock_brokers.instruments.ticks import base
from stock_brokers.instruments.ticks.base import (
    InstrumentPlan,
)
from stock_brokers.instruments.ticks.groww import (
    GrowwTickNormalizer,
)
from stock_brokers.instruments.ticks.utilities import sessions

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class RelianceTickExample:
    """Normalizes one Groww tick through a hand-built plan and prints the result.

    Attributes:
        normalizer (GrowwTickNormalizer): The normalizer being shown.
        received_at (float): When the tick was received, in epoch seconds.
        tick (dict): The tick as the market feed published it.
        plan (InstrumentPlan): The plan for the tick's instrument.
    """

    def __init__(self):
        """Builds the normalizer, the tick and its plan.

        Returns:
            None: This method returns nothing.
        """
        self.normalizer = GrowwTickNormalizer()
        received = datetime.datetime(2026, 9, 15, 11, 5, tzinfo=INDIA)
        self.received_at = received.timestamp()
        self.tick = {
            'instrument_token': 'NSE|CASH|2885',
            'last_price': 1262.7,
            'last_quantity': 15,
            'average_price': 1263.84,
            'volume': 1885670,
            'buy_quantity': 402113,
            'sell_quantity': 388921,
            'ohlc': {
                'open': 1266.4,
                'high': 1267.4,
                'low': 1261.5,
                'close': 1262.7,
            },
            'oi': None,
            'oi_day_high': None,
            'oi_day_low': None,
            'last_trade_time': self.received_at - 2.0,
            'exchange_timestamp': self.received_at - 1.0,
            'received_at': self.received_at,
            'depth': {
                'buy': [
                    {
                        'price': 1262.6,
                        'quantity': 120,
                        'orders': 4,
                    },
                    {
                        'price': 1262.5,
                        'quantity': 340,
                        'orders': 9,
                    },
                ],
                'sell': [
                    {
                        'price': 1262.7,
                        'quantity': 95,
                        'orders': 3,
                    },
                    {
                        'price': 1262.8,
                        'quantity': 210,
                        'orders': 6,
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
        segment = 'nse_equities'
        lot_size = 1
        broker_lot_size = 1
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
            'segment': 'nse_equities',
            'shape': 'security',
            'symbol': 'RELIANCE',
            'underlying_symbol': None,
            'expiry_date': None,
            'strike_price': None,
            'option_type': None,
        }
        instrument_id = '11111111-1111-5111-8111-000000000102'
        broker_token = '2885'
        return InstrumentPlan(
            instrument_id=instrument_id,
            broker=GrowwTickNormalizer.BROKER_NAME,
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
            trusts_last_trade_time=GrowwTickNormalizer.TRUSTS_LAST_TRADE_TIME,
            trusts_exchange_time=GrowwTickNormalizer.TRUSTS_EXCHANGE_TIME,
            identity_json=base.identity_json(
                instrument_id,
                GrowwTickNormalizer.BROKER_NAME,
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
    RelianceTickExample().run()
