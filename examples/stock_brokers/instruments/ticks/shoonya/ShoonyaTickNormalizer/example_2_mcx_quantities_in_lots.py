"""Normalizes one Shoonya tick for an MCX natural gas future, whose quantities arrive in lots.

Noren reports MCX quantities in lots, so the plan multiplies each by the contract's 1250-unit lot. Commodity futures have traded below zero, so the plan for an MCX future allows negative prices. Noren's `close` is the previous close only while the session runs, so `reported_close` is kept before the close and dropped after it.

The plan that `normalize` applies is normally compiled by `TickResolver` from the mapping cache. This program builds it by hand with the same rules, asking the normalizer how it reports each quantity field and when its close may be trusted, so it needs no database. The tick is shaped like the ones the broker's market feed publishes, with fixed times, so the output is the same on every run. The program normalizes the tick twice, once as received before the session's close and once as received after it, which only changes whether `reported_close` is kept. Order book levels are printed as (price, quantity, orders).

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/shoonya/ShoonyaTickNormalizer/example_2_mcx_quantities_in_lots.py
"""

import datetime
import zoneinfo

from stock_brokers.instruments.ticks import base
from stock_brokers.instruments.ticks.base import (
    InstrumentPlan,
)
from stock_brokers.instruments.ticks.shoonya import (
    ShoonyaTickNormalizer,
)
from stock_brokers.instruments.ticks.utilities import sessions

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class NaturalGasTickExample:
    """Normalizes one Shoonya tick through a hand-built plan and prints the result.

    Attributes:
        normalizer (ShoonyaTickNormalizer): The normalizer being shown.
        received_at (float): When the tick was received, in epoch seconds.
        tick (dict): The tick as the market feed published it.
        plan (InstrumentPlan): The plan for the tick's instrument.
    """

    def __init__(self):
        """Builds the normalizer, the tick and its plan.

        Returns:
            None: This method returns nothing.
        """
        self.normalizer = ShoonyaTickNormalizer()
        received = datetime.datetime(2026, 9, 15, 21, 30, tzinfo=INDIA)
        self.received_at = received.timestamp()
        self.tick = {
            'instrument_token': 'MCX|440001',
            'last_price': 268.4,
            'last_quantity': 1,
            'average_price': 267.9,
            'volume': 88214,
            'buy_quantity': 1520,
            'sell_quantity': 1733,
            'ohlc': {
                'open': 265.1,
                'high': 270.2,
                'low': 264.8,
                'close': 266.3,
            },
            'oi': 21440,
            'oi_day_high': 22010,
            'oi_day_low': 20985,
            'last_trade_time': self.received_at - 2.0,
            'exchange_timestamp': self.received_at - 1.0,
            'received_at': self.received_at,
            'depth': {
                'buy': [
                    {
                        'price': 268.3,
                        'quantity': 4,
                        'orders': 3,
                    },
                    {
                        'price': 268.2,
                        'quantity': 9,
                        'orders': 5,
                    },
                ],
                'sell': [
                    {
                        'price': 268.4,
                        'quantity': 2,
                        'orders': 1,
                    },
                    {
                        'price': 268.5,
                        'quantity': 7,
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
        exchange = 'mcx'
        segment = 'mcx_commodity_futures'
        lot_size = 1250
        broker_lot_size = 1250
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
            'exchange': 'mcx',
            'segment': 'mcx_commodity_futures',
            'shape': 'future',
            'symbol': 'NATURALGAS26SEPFUT',
            'underlying_symbol': 'NATURALGAS',
            'expiry_date': '2026-09-25',
            'strike_price': None,
            'option_type': None,
        }
        instrument_id = '11111111-1111-5111-8111-000000000103'
        broker_token = '440001'
        return InstrumentPlan(
            instrument_id=instrument_id,
            broker=ShoonyaTickNormalizer.BROKER_NAME,
            broker_token=broker_token,
            exchange=exchange,
            segment=segment,
            shape=identity['shape'],
            session=sessions.session_for(segment),
            lot_size=lot_size,
            multipliers=multipliers,
            price_decimals=2,
            negative_prices=True,
            close_policy=self.normalizer.close_policy(exchange),
            has_open_interest=identity['shape'] != 'security',
            trusts_last_trade_time=ShoonyaTickNormalizer.TRUSTS_LAST_TRADE_TIME,
            trusts_exchange_time=ShoonyaTickNormalizer.TRUSTS_EXCHANGE_TIME,
            identity_json=base.identity_json(
                instrument_id,
                ShoonyaTickNormalizer.BROKER_NAME,
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
    NaturalGasTickExample().run()
