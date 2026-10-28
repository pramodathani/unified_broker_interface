"""Normalizes one Kotak tick for an MCX crude oil future, whose quantities arrive in lots, as at Zerodha.

On Kotak's SFeed market feed every MCX quantity - last quantity, volume, total buy and sell quantity, open interest and every order book quantity - is in lots, exactly as Zerodha reports it. On 2026-10-28 CRUDEOIL NOV read volume 3528 and open interest 13801 at both brokers. The normalizer therefore reports those fields as `lots`, so the plan multiplies each by the contract's 100-barrel lot. Kotak's own lot size for CRUDEOIL is also 100, but it no longer enters the multiplier. Kotak's `close` is always the previous close, so `reported_close` is kept both before and after the session ends.

The plan that `normalize` applies is normally compiled by `TickResolver` from the mapping cache. This program builds it by hand with the same rules, asking the normalizer how it reports each quantity field and when its close may be trusted, so it needs no database. The tick is shaped like the ones the broker's market feed publishes, with the volume, open interest and previous close measured on 2026-10-28 and fixed times, so the output is the same on every run. The program normalizes the tick twice, once as received before the session's close and once as received after it, which only changes whether `reported_close` is kept. Order book levels are printed as (price, quantity, orders).

Notice that a volume of 3528 lots becomes 352800 barrels and an open interest of 13801 lots becomes 1380100. The retired HSM feed sent the volume as 352800 already, Kotak's lots times its own lot size, which is why the normalizer used to divide by that lot size first.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/kotak/KotakTickNormalizer/example_2_mcx_quantities_in_lots.py
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


class CrudeOilTickExample:
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
        received = datetime.datetime(2026, 10, 28, 14, 20, tzinfo=INDIA)
        self.received_at = received.timestamp()
        self.tick = {
            'instrument_token': 'mcx_fo|440001',
            'last_price': 9518.0,
            'last_quantity': 2,
            'average_price': 9507.35,
            'volume': 3528,
            'buy_quantity': 1874,
            'sell_quantity': 2216,
            'ohlc': {
                'open': 9490.0,
                'high': 9541.0,
                'low': 9472.0,
                'close': 9498.0,
            },
            'oi': 13801,
            'oi_day_high': None,
            'oi_day_low': None,
            'last_trade_time': self.received_at - 2.0,
            'exchange_timestamp': self.received_at - 1.0,
            'received_at': self.received_at,
            'depth': {
                'buy': [
                    {
                        'price': 9517.0,
                        'quantity': 3,
                        'orders': 2,
                    },
                    {
                        'price': 9516.0,
                        'quantity': 7,
                        'orders': 4,
                    },
                ],
                'sell': [
                    {
                        'price': 9518.0,
                        'quantity': 1,
                        'orders': 1,
                    },
                    {
                        'price': 9519.0,
                        'quantity': 5,
                        'orders': 3,
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
        broker_lot_size = 100
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
            'symbol': 'CRUDEOIL26NOVFUT',
            'underlying_symbol': 'CRUDEOIL',
            'expiry_date': '2026-11-19',
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
    CrudeOilTickExample().run()
