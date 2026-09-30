"""Shows every step at which the tick pipeline drops a tick, and a previous close seeded from before the process started.

The pipeline refuses the cheapest things first. A tick with no receipt time, or whose token resolves to no plan, is counted as `unresolved`. One received outside its instrument's session window, such as a Sunday reconnect replaying Friday's prices, is `out_of_session`. One from a broker that does not own the instrument is `not_owner`, unless it caused an ownership change, which is still returned so it can be recorded. One without a usable last price is `no_price`.

Groww's `close` is never the previous session's close, so a Groww tick has no previous close of its own. The live service remembers the owner's previous close from earlier in the day and, after a restart, seeds it from storage with `seed_previous_close`; the program seeds one so the change percentage can be computed. A seeded close only counts on the India day it was recorded for.

The resolver, the ownership engine and the clock are small stand-ins defined here: the resolver hands out hand-built plans for one Zerodha and one Groww token for the same instrument, and the ownership engine makes Groww the owner, reporting a change of owner on Groww's first tick. That first tick has a zero price, so it is not written, but the change of owner it caused is still returned. The session gate uses an empty calendar. All times are fixed, and no data store is involved.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/utilities/pipeline/TickPipeline/example_2_ticks_that_are_dropped.py
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
    """A stand-in for `TickResolver` that knows RELIANCE at Zerodha and at Groww.

    Attributes:
        plans (dict): (broker, token) to the plan for it.
    """

    def __init__(self):
        """Builds the two plans.

        Returns:
            None: This method returns nothing.
        """
        self.plans = {
            ('zerodha', 738561): self.plan(ZerodhaTickNormalizer(), 'zerodha', '738561'),
            ('groww', 'NSE|CASH|2885'): self.plan(GrowwTickNormalizer(), 'groww', '2885'),
        }

    def plan(self, normalizer, broker, broker_token):
        """Builds the plan for RELIANCE at one broker.

        Args:
            normalizer (TickNormalizer): The broker's normalizer, which decides the close policy and trusted times.
            broker (str): The broker name.
            broker_token (str): The broker's token.

        Returns:
            InstrumentPlan: The plan.
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
        return InstrumentPlan(
            instrument_id=RELIANCE_ID,
            broker=broker,
            broker_token=broker_token,
            exchange='nse',
            segment='nse_equities',
            shape='security',
            session=sessions.session_for('nse_equities'),
            lot_size=1,
            multipliers=multipliers,
            price_decimals=2,
            negative_prices=False,
            close_policy=normalizer.close_policy('nse'),
            has_open_interest=False,
            trusts_last_trade_time=normalizer.TRUSTS_LAST_TRADE_TIME,
            trusts_exchange_time=normalizer.TRUSTS_EXCHANGE_TIME,
            identity_json=base.identity_json(RELIANCE_ID, broker, broker_token, identity, 1),
        )

    def plan_for(self, broker, instrument_token, now):
        """Hands out a plan by broker and token.

        Args:
            broker (str): The broker the tick came from.
            instrument_token (int | str): The tick's token.
            now (float): The current instant.

        Returns:
            InstrumentPlan | None: The plan, or None for a token it does not know.
        """
        return self.plans.get((broker, instrument_token))


class GrowwOwnsReliance:
    """A stand-in ownership engine under which Groww owns every instrument.

    Attributes:
        claimed (set): Instruments Groww has already been recorded as owning.
    """

    def __init__(self):
        """Starts with nothing claimed.

        Returns:
            None: This method returns nothing.
        """
        self.claimed = set()

    def observe(self, broker, socket, instrument_id, exchange, received_at, window_end):
        """Writes Groww's ticks and reports the change of owner on its first one.

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
        if broker != 'groww':
            return False, []
        if instrument_id in self.claimed:
            return True, []
        self.claimed.add(instrument_id)
        change = {
            'instrument_id': instrument_id,
            'owner': 'groww',
        }
        return True, [
            change,
        ]


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


class TicksThatAreDroppedExample:
    """Sends ticks that are dropped at each step, then two Groww ticks, and prints the counts.

    Attributes:
        tuesday (float): 10:00 India time on Tuesday 2026-09-15, in epoch seconds.
        pipeline (TickPipeline): The pipeline being shown.
    """

    def __init__(self):
        """Builds the pipeline from its stand-in parts.

        Returns:
            None: This method returns nothing.
        """
        moment = datetime.datetime(2026, 9, 15, 10, 0, tzinfo=INDIA)
        self.tuesday = moment.timestamp()
        normalizers = {
            'zerodha': ZerodhaTickNormalizer(),
            'groww': GrowwTickNormalizer(),
        }
        self.pipeline = TickPipeline(
            StandInResolver(),
            GrowwOwnsReliance(),
            normalizers,
            gate=SessionGate(TradingCalendar.empty()),
            clock=FixedClock(self.tuesday).now,
        )

    def tick(self, token, received_at, last_price):
        """Builds a tick for RELIANCE.

        Args:
            token (int | str): The broker's token as the feed spells it.
            received_at (float | None): When it arrived, or None for a tick missing its receipt time.
            last_price (float | None): The last traded price.

        Returns:
            dict: The tick.
        """
        return {
            'instrument_token': token,
            'last_price': last_price,
            'volume': 1885670,
            'ohlc': {
                'open': 1266.4,
                'close': 1262.7,
            },
            'received_at': received_at,
        }

    def send(self, label, broker, tick):
        """Sends one tick and prints the outcome.

        Args:
            label (str): What the tick is meant to show.
            broker (str): The broker whose feed published it.
            tick (dict): The tick.

        Returns:
            None: This method returns nothing.
        """
        output = self.pipeline.process(broker, 'quotes', tick)
        if output is None:
            print(f'{label}: dropped')
            return
        if output.row is None:
            print(f'{label}: not written, ownership changes {output.transitions}')
            return
        print(f'{label}: written, last_price {output.row[5]}, previous_close {output.row[14]}, change_percent {output.row[15]}, ownership changes {output.transitions}')

    def run(self):
        """Prints each outcome and the counts per step.

        Returns:
            None: This method returns nothing.
        """
        sunday = datetime.datetime(2026, 9, 13, 10, 0, tzinfo=INDIA).timestamp()
        monday = datetime.datetime(2026, 9, 14, 15, 30, tzinfo=INDIA).timestamp()
        self.send('No receipt time', 'zerodha', self.tick(738561, None, 1262.7))
        self.send('Unknown token', 'zerodha', self.tick(999, self.tuesday, 1262.7))
        self.send('Sunday replay', 'zerodha', self.tick(738561, sunday, 1262.7))
        self.send('Zerodha, not the owner', 'zerodha', self.tick(738561, self.tuesday, 1262.7))
        self.send('Groww, zero price', 'groww', self.tick('NSE|CASH|2885', self.tuesday, 0))
        self.send('Groww, no close yet', 'groww', self.tick('NSE|CASH|2885', self.tuesday + 1, 1262.7))
        self.pipeline.seed_previous_close(RELIANCE_ID, monday, 1257.5)
        self.send('Groww, after seeding Monday close', 'groww', self.tick('NSE|CASH|2885', self.tuesday + 2, 1262.9))
        self.pipeline.seed_previous_close(RELIANCE_ID, self.tuesday, 1257.5)
        self.send('Groww, after seeding it for today', 'groww', self.tick('NSE|CASH|2885', self.tuesday + 3, 1263.1))
        for step, count in sorted(self.pipeline.counts.items()):
            print(f'{step}: {count}')


if __name__ == '__main__':
    TicksThatAreDroppedExample().run()
