"""Shows the rules the base class's `normalize` applies to every broker's ticks, by feeding it awkward ticks.

`TickNormalizer.normalize` is shared by every broker. Beyond multiplying quantities, it refuses values that cannot be right: a tick with no last price, or a zero or negative one where negative prices are impossible, gives `None`; a timestamp more than seven days before the tick was received, or more than five seconds after it, is dropped as a clock nobody corrected; an order book level without both a price and a quantity is dropped and the book is cut to five levels; and a quantity whose multiplier is unknown is left as `None` rather than guessed.

The program uses a tiny subclass for an imaginary broker, because `normalize` needs only a plan and the broker's class attributes. Two plans are built by hand: an NSE share, and an MCX future whose lot size is unknown. Every time is fixed, so the output is the same on every run, and nothing touches a data store or a broker.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/base/TickNormalizer/example_2_what_normalize_refuses.py
"""

import datetime
import zoneinfo

from stock_brokers.instruments.ticks import base
from stock_brokers.instruments.ticks.base import (
    InstrumentPlan,
    TickNormalizer,
)
from stock_brokers.instruments.ticks.utilities import sessions

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class ImaginaryBrokerTickNormalizer(TickNormalizer):
    """Normalizes ticks from an imaginary broker that reports MCX quantities in lots."""

    BROKER_NAME = 'imaginary'
    LOT_FIELDS = {
        'mcx': frozenset(base.QUANTITY_FIELDS),
    }

    def feed_key(self, instrument_token):
        """Places every token among NSE shares, which is all this example needs.

        Args:
            instrument_token (str): The tick's token.

        Returns:
            FeedKey: The key.
        """
        segments = (
            'nse_equities',
        )
        return base.FeedKey(str(instrument_token), segments)


class WhatNormalizeRefusesExample:
    """Normalizes a series of awkward ticks and prints what survives.

    Attributes:
        normalizer (ImaginaryBrokerTickNormalizer): The normalizer being shown.
        received_at (float): When every tick was received, in epoch seconds.
    """

    def __init__(self):
        """Builds the normalizer and fixes the receipt time.

        Returns:
            None: This method returns nothing.
        """
        self.normalizer = ImaginaryBrokerTickNormalizer()
        received = datetime.datetime(2026, 9, 15, 11, 5, tzinfo=INDIA)
        self.received_at = received.timestamp()

    def plan(self, exchange, segment, shape, lot_size):
        """Builds a plan the way the resolver would, using the normalizer's rules.

        Args:
            exchange (str): The canonical exchange.
            segment (str): The canonical segment.
            shape (str): "security", "future" or "option".
            lot_size (int | None): Units per lot, or None when unknown.

        Returns:
            InstrumentPlan: The plan.
        """
        multipliers = {}
        for field in base.QUANTITY_FIELDS:
            if self.normalizer.quantity_basis(exchange, field) == base.BASIS_UNITS:
                multipliers[field] = 1
            else:
                multipliers[field] = lot_size
        return InstrumentPlan(
            instrument_id='11111111-1111-5111-8111-000000000102',
            broker='imaginary',
            broker_token='2885',
            exchange=exchange,
            segment=segment,
            shape=shape,
            session=sessions.session_for(segment),
            lot_size=lot_size,
            multipliers=multipliers,
            price_decimals=2,
            negative_prices=shape != 'security' and exchange == 'mcx',
            close_policy=self.normalizer.close_policy(exchange),
            has_open_interest=shape != 'security',
            trusts_last_trade_time=True,
            trusts_exchange_time=True,
            identity_json='"instrument_id":"11111111-1111-5111-8111-000000000102"',
        )

    def run(self):
        """Prints what `normalize` makes of each awkward tick.

        Returns:
            None: This method returns nothing.
        """
        share = self.plan('nse', 'nse_equities', 'security', 1)
        impossible_prices = [
            None,
            0,
            -3.5,
        ]
        for last_price in impossible_prices:
            outcome = self.normalizer.normalize(
                {
                    'last_price': last_price,
                    'received_at': self.received_at,
                },
                share,
                True,
            )
            print(f'last_price {last_price!r} -> {outcome}')
        eight_days = 8 * 86400
        tick = {
            'last_price': 1262.70000001,
            'volume': 1885670.0,
            'last_trade_time': self.received_at - eight_days,
            'exchange_timestamp': self.received_at + 60,
            'received_at': self.received_at,
            'oi': 0,
            'depth': {
                'buy': [
                    {
                        'price': 1262.6,
                        'quantity': 120,
                        'orders': 4.0,
                    },
                    {
                        'price': 0.0,
                        'quantity': 0,
                        'orders': 0,
                    },
                    {
                        'price': 1262.4,
                        'quantity': 0,
                        'orders': 0,
                    },
                    {
                        'price': 1262.3,
                        'quantity': 50,
                        'orders': None,
                    },
                ],
            },
        }
        values = self.normalizer.normalize(tick, share, True)
        print(f"Share: last_price {values['last_price']}, volume {values['volume']}, oi {values['oi']}")
        print(f"Share: last_trade_time eight days old -> {values['last_trade_time']}, exchange_time a minute ahead -> {values['exchange_time']}")
        print(f"Share: bids {values['bids']}, asks {values['asks']}")
        print(f"Share: close policy {share.close_policy}, reported_close {values['reported_close']}")
        future = self.plan('mcx', 'mcx_commodity_futures', 'future', None)
        values = self.normalizer.normalize(
            {
                'last_price': -12.5,
                'volume': 400,
                'oi': 900,
                'received_at': self.received_at,
            },
            future,
            True,
        )
        print(f"Future with an unknown lot: last_price {values['last_price']}, volume {values['volume']}, oi {values['oi']}")


if __name__ == '__main__':
    WhatNormalizeRefusesExample().run()
