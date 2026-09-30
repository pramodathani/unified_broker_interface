"""Adds a normalizer for a new Noren broker in one line, and normalizes an NCDEX tick with it.

A broker that runs on the Noren platform needs nothing of its own but a name: `FlattradeTickNormalizer` and `ShoonyaTickNormalizer` are both a subclass of `NorenTickNormalizer` that sets `BROKER_NAME`. This program does the same for an imaginary Noren broker, then uses what it inherits: `feed_key` places an NCDEX token, `quantity_basis` says NCDEX quantities arrive in lots, and `close_policy` says `close` is the previous close only before the session ends.

The plan that `normalize` applies is normally compiled by `TickResolver` from the mapping cache; here it is built by hand with the same rules, for an NCDEX guar seed future with a lot of 5 units, so no database is needed. The tick is received at 20:00 India time, inside NCDEX's evening session, and is normalized twice, as received before the session's close and after it, which only changes whether `reported_close` is kept.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/noren/NorenTickNormalizer/example_2_a_new_noren_broker.py
"""

import datetime
import zoneinfo

from stock_brokers.instruments.ticks import base
from stock_brokers.instruments.ticks.base import (
    InstrumentPlan,
)
from stock_brokers.instruments.ticks.noren import (
    NorenTickNormalizer,
)
from stock_brokers.instruments.ticks.utilities import sessions

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class ImaginaryNorenTickNormalizer(NorenTickNormalizer):
    """Normalizes ticks from an imaginary broker on the Noren platform."""

    BROKER_NAME = 'imaginary_noren'


class NewNorenBrokerExample:
    """Normalizes one NCDEX tick with the new broker's normalizer.

    Attributes:
        normalizer (ImaginaryNorenTickNormalizer): The normalizer being shown.
        received_at (float): When the tick was received, in epoch seconds.
        tick (dict): The tick as the market feed published it.
    """

    def __init__(self):
        """Builds the normalizer and the tick.

        Returns:
            None: This method returns nothing.
        """
        self.normalizer = ImaginaryNorenTickNormalizer()
        received = datetime.datetime(2026, 9, 15, 20, 0, tzinfo=INDIA)
        self.received_at = received.timestamp()
        self.tick = {
            'instrument_token': 'NCX|12345',
            'last_price': 5412.0,
            'last_quantity': 2,
            'volume': 3120,
            'ohlc': {
                'open': 5390.0,
                'high': 5430.0,
                'low': 5381.0,
                'close': 5377.0,
            },
            'oi': 14880,
            'last_trade_time': self.received_at - 3.0,
            'exchange_timestamp': self.received_at - 1.0,
            'received_at': self.received_at,
        }

    def build_plan(self, broker_token):
        """Compiles the plan for the guar seed future the way the resolver would.

        Args:
            broker_token (str): The token the mappings were searched with.

        Returns:
            InstrumentPlan: The plan.
        """
        exchange = 'ncdex'
        segment = 'ncdex_commodity_futures'
        lot_size = 5
        multipliers = {}
        for field in base.QUANTITY_FIELDS:
            if self.normalizer.quantity_basis(exchange, field) == base.BASIS_LOTS:
                multipliers[field] = lot_size
            else:
                multipliers[field] = 1
        identity = {
            'exchange': exchange,
            'segment': segment,
            'shape': 'future',
            'symbol': 'GUARSEED10OCT2026',
        }
        instrument_id = '11111111-1111-5111-8111-000000000110'
        return InstrumentPlan(
            instrument_id=instrument_id,
            broker=ImaginaryNorenTickNormalizer.BROKER_NAME,
            broker_token=broker_token,
            exchange=exchange,
            segment=segment,
            shape='future',
            session=sessions.session_for(segment),
            lot_size=lot_size,
            multipliers=multipliers,
            price_decimals=2,
            negative_prices=True,
            close_policy=self.normalizer.close_policy(exchange),
            has_open_interest=True,
            trusts_last_trade_time=True,
            trusts_exchange_time=True,
            identity_json=base.identity_json(
                instrument_id,
                ImaginaryNorenTickNormalizer.BROKER_NAME,
                broker_token,
                identity,
                lot_size,
            ),
        )

    def run(self):
        """Prints the feed key, the rules and the normalized values.

        Returns:
            None: This method returns nothing.
        """
        feed_key = self.normalizer.feed_key(self.tick['instrument_token'])
        print(f'Broker: {ImaginaryNorenTickNormalizer.BROKER_NAME}')
        print(f'Token {self.tick["instrument_token"]!r}: broker_token {feed_key.broker_token!r}, {len(feed_key.segments)} segments starting with {feed_key.segments[0]}')
        print(f"NCDEX volume is reported in {self.normalizer.quantity_basis('ncdex', 'volume')}")
        print(f"NCDEX close policy: {self.normalizer.close_policy('ncdex')}")
        plan = self.build_plan(feed_key.broker_token)
        before_close = self.normalizer.normalize(self.tick, plan, True)
        after_close = self.normalizer.normalize(self.tick, plan, False)
        print(f"last_price {before_close['last_price']}, last_quantity {before_close['last_quantity']}, volume {before_close['volume']}, oi {before_close['oi']}")
        print(f"reported_close before the close {before_close['reported_close']}, after it {after_close['reported_close']}")
        gate = sessions.SessionGate(sessions.TradingCalendar.empty())
        print(f'Received inside the NCDEX window: {gate.in_window("ncdex", plan.session, self.received_at)}')


if __name__ == '__main__':
    NewNorenBrokerExample().run()
