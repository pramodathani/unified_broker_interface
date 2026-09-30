"""Takes three Zerodha ticks for RELIANCE through the tick pipeline, and flags the last quote stale.

`TickPipeline.process` takes one broker tick through every step the unified tick service applies: resolve the token to a plan, drop it outside the session window, ask the ownership engine whether this broker's ticks are written, normalize it, set the previous close and the change from it, and drop it if nothing but the clock changed. A survivor becomes a quote (the JSON the unified cache stores and publishes) and a row for `unified.ticks`.

The pipeline is built from parts that the live service backs with Redis and the database, so this program passes small stand-ins: a resolver that hands out one hand-built plan, an ownership engine under which Zerodha owns every instrument, and a clock fixed at one instant for the quote's `unified_at`. The session gate uses an empty calendar, so the Tuesday used here is an ordinary trading day. The second tick repeats the first one's values a second later, so it is dropped as a duplicate; the third has a new price and is written. `stale_quote` then marks the last quote stale, which the service does when an instrument's owner stops sending ticks and there is no backup.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/utilities/pipeline/TickPipeline/example_1_ticks_into_quotes.py
"""

import datetime
import zoneinfo

from stock_brokers.instruments.ticks import base
from stock_brokers.instruments.ticks.base import (
    InstrumentPlan,
)
from stock_brokers.instruments.ticks.utilities import pipeline
from stock_brokers.instruments.ticks.utilities import sessions
from stock_brokers.instruments.ticks.utilities.pipeline import (
    TickPipeline,
)
from stock_brokers.instruments.ticks.utilities.sessions import (
    SessionGate,
    TradingCalendar,
)
from stock_brokers.instruments.ticks.zerodha import (
    ZerodhaTickNormalizer,
)

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')
RELIANCE_ID = '11111111-1111-5111-8111-000000000102'


class StandInResolver:
    """A stand-in for `TickResolver` that knows one Zerodha token.

    Attributes:
        plan (InstrumentPlan): The plan for RELIANCE at Zerodha.
    """

    def __init__(self):
        """Builds the plan for RELIANCE on NSE.

        Returns:
            None: This method returns nothing.
        """
        identity = {
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
            'symbol': 'RELIANCE',
        }
        multipliers = {}
        for field in base.QUANTITY_FIELDS:
            multipliers[field] = 1
        self.plan = InstrumentPlan(
            instrument_id=RELIANCE_ID,
            broker='zerodha',
            broker_token='738561',
            exchange='nse',
            segment='nse_equities',
            shape='security',
            session=sessions.session_for('nse_equities'),
            lot_size=1,
            multipliers=multipliers,
            price_decimals=2,
            negative_prices=False,
            close_policy=base.CLOSE_ALWAYS,
            has_open_interest=False,
            trusts_last_trade_time=True,
            trusts_exchange_time=True,
            identity_json=base.identity_json(RELIANCE_ID, 'zerodha', '738561', identity, 1),
        )

    def plan_for(self, broker, instrument_token, now):
        """Hands out the plan for Zerodha token 738561.

        Args:
            broker (str): The broker the tick came from.
            instrument_token (int | str): The tick's token.
            now (float): The current instant.

        Returns:
            InstrumentPlan | None: The plan, or None for any other token.
        """
        if broker == 'zerodha' and instrument_token == 738561:
            return self.plan
        return None


class ZerodhaOwnsEverything:
    """A stand-in for the ownership engine under which Zerodha owns every instrument."""

    def observe(self, broker, socket, instrument_id, exchange, received_at, window_end):
        """Says whether a broker's tick is written.

        Args:
            broker (str): The broker whose tick arrived.
            socket (str): The socket it arrived on.
            instrument_id (str): The instrument.
            exchange (str): The canonical exchange.
            received_at (float): When it arrived.
            window_end (float): When the session window around it closes.

        Returns:
            tuple: (whether to write the tick, a list of ownership changes).
        """
        return broker == 'zerodha', []


class FixedClock:
    """A clock that always answers the same instant.

    Attributes:
        instant (float): The instant, in epoch seconds.
    """

    def __init__(self, instant):
        """Remembers the instant.

        Args:
            instant (float): The instant, in epoch seconds.

        Returns:
            None: This method returns nothing.
        """
        self.instant = instant

    def now(self):
        """Answers the instant.

        Returns:
            float: The instant, in epoch seconds.
        """
        return self.instant


class TicksIntoQuotesExample:
    """Sends three ticks through a pipeline and prints what comes out.

    Attributes:
        start (float): When the first tick arrives, in epoch seconds.
        pipeline (TickPipeline): The pipeline being shown.
    """

    def __init__(self):
        """Builds the pipeline from its stand-in parts.

        Returns:
            None: This method returns nothing.
        """
        moment = datetime.datetime(2026, 9, 15, 10, 0, tzinfo=INDIA)
        self.start = moment.timestamp()
        normalizers = {
            'zerodha': ZerodhaTickNormalizer(),
        }
        self.pipeline = TickPipeline(
            StandInResolver(),
            ZerodhaOwnsEverything(),
            normalizers,
            gate=SessionGate(TradingCalendar.empty()),
            clock=FixedClock(self.start + 0.25).now,
        )

    def tick(self, seconds_later, last_price):
        """Builds a Kite tick for RELIANCE.

        Args:
            seconds_later (int): Seconds after the first tick that this one arrives.
            last_price (float): The last traded price.

        Returns:
            dict: The tick.
        """
        received_at = self.start + seconds_later
        return {
            'instrument_token': 738561,
            'last_price': last_price,
            'last_quantity': 15,
            'average_price': 1263.84,
            'volume': 1885670,
            'ohlc': {
                'open': 1266.4,
                'high': 1267.4,
                'low': 1261.5,
                'close': 1274.0,
            },
            'last_trade_time': received_at - 1.0,
            'exchange_timestamp': received_at - 0.5,
            'received_at': received_at,
            'depth': {
                'buy': [
                    {
                        'price': 1262.6,
                        'quantity': 120,
                        'orders': 4,
                    },
                ],
                'sell': [
                    {
                        'price': 1262.7,
                        'quantity': 95,
                        'orders': 3,
                    },
                ],
            },
        }

    def run(self):
        """Prints the outcome of each tick, the stale quote and the step counts.

        Returns:
            None: This method returns nothing.
        """
        first = self.pipeline.process('zerodha', 'quotes', self.tick(0, 1262.7))
        print(f'First tick written for {first.instrument_id}, ownership changes {first.transitions}')
        print(f'Quote: {first.quote}')
        print('Row, first twenty columns:')
        for index in range(20):
            print(f'  {pipeline.TICK_COLUMNS[index]}: {first.row[index]}')
        repeat = self.pipeline.process('zerodha', 'quotes', self.tick(1, 1262.7))
        print(f'Same values a second later: {repeat}')
        moved = self.pipeline.process('zerodha', 'quotes', self.tick(2, 1263.5))
        print(f'New price two seconds later: row last_price {moved.row[5]}, previous_close {moved.row[14]}, change_percent {moved.row[15]}')
        stale = self.pipeline.stale_quote(RELIANCE_ID, self.start + 120)
        print(f'Stale quote ends with: {stale[-60:]}')
        print(f"Stale quote for an instrument never written: {self.pipeline.stale_quote('11111111-1111-5111-8111-000000000999', self.start)}")
        print(f'Counts: {dict(self.pipeline.counts)}')


if __name__ == '__main__':
    TicksIntoQuotesExample().run()
