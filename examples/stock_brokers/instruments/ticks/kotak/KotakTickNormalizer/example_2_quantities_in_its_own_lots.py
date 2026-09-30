"""Normalizes one Kotak tick for an MCX gold future, whose quantities are in Kotak's own lots.

Kotak's MCX quantities are lots times Kotak's own lot size, which for GOLD is 1 where the contract's is 100. The normalizer reports those fields as `broker_lots`, so the plan's multiplier is the authoritative lot divided by Kotak's, 100, and a last quantity of 1 becomes 100 units. Kotak's `close` is always the previous close, so `reported_close` is kept both before and after the session ends.

The plan that `normalize` applies is normally compiled by `TickResolver` from the mapping cache. This program builds it by hand with the same rules, asking the normalizer how it reports each quantity field and when its close may be trusted, so it needs no database. The tick is shaped like the ones the broker's market feed publishes, with fixed times, so the output is the same on every run. The program normalizes the tick twice, once as received before the session's close and once as received after it, which only changes whether `reported_close` is kept. Order book levels are printed as (price, quantity, orders).

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/kotak/KotakTickNormalizer/example_2_quantities_in_its_own_lots.py
"""

import datetime
import zoneinfo

from stock_brokers.instruments.ticks import base
from stock_brokers.instruments.ticks.base import (
    InstrumentPlan,
)
from stock_brokers.instruments.ticks.kotak import (
    KotakTickNormalizer,
)
from stock_brokers.instruments.ticks.utilities import sessions

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class GoldTickExample:
    """Normalizes one Kotak tick through a hand-built plan and prints the result.

    Attributes:
        normalizer (KotakTickNormalizer): The normalizer being shown.
        received_at (float): When the tick was received, in epoch seconds.
        tick (dict): The tick as the market feed published it.
        plan (InstrumentPlan): The plan for the tick's instrument.
    """

    def __init__(self):
        """Builds the normalizer, the tick and its plan.

        Returns:
            None: This method returns nothing.
        """
        self.normalizer = KotakTickNormalizer()
        received = datetime.datetime(2026, 9, 15, 14, 20, tzinfo=INDIA)
        self.received_at = received.timestamp()
        self.tick = {
            'instrument_token': 'mcx_fo|440001',
            'last_price': 109850.0,
            'last_quantity': 1,
            'average_price': 109712.4,
            'volume': 12840,
            'buy_quantity': 322,
            'sell_quantity': 417,
            'ohlc': {
                'open': 109500.0,
                'high': 110020.0,
                'low': 109388.0,
                'close': 109460.0,
            },
            'oi': 15632,
            'oi_day_high': 15890,
            'oi_day_low': 15411,
            'last_trade_time': self.received_at - 2.0,
            'exchange_timestamp': self.received_at - 1.0,
            'received_at': self.received_at,
            'depth': {
                'buy': [
                    {
                        'price': 109848.0,
                        'quantity': 2,
                        'orders': 2,
                    },
                    {
                        'price': 109845.0,
                        'quantity': 5,
                        'orders': 3,
                    },
                ],
                'sell': [
                    {
                        'price': 109850.0,
                        'quantity': 1,
                        'orders': 1,
                    },
                    {
                        'price': 109853.0,
                        'quantity': 4,
                        'orders': 2,
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
        lot_size = 100
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
            'exchange': 'mcx',
            'segment': 'mcx_commodity_futures',
            'shape': 'future',
            'symbol': 'GOLD26OCTFUT',
            'underlying_symbol': 'GOLD',
            'expiry_date': '2026-10-05',
            'strike_price': None,
            'option_type': None,
        }
        instrument_id = '11111111-1111-5111-8111-000000000106'
        broker_token = '440001'
        return InstrumentPlan(
            instrument_id=instrument_id,
            broker=KotakTickNormalizer.BROKER_NAME,
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
            trusts_last_trade_time=KotakTickNormalizer.TRUSTS_LAST_TRADE_TIME,
            trusts_exchange_time=KotakTickNormalizer.TRUSTS_EXCHANGE_TIME,
            identity_json=base.identity_json(
                instrument_id,
                KotakTickNormalizer.BROKER_NAME,
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
    GoldTickExample().run()
