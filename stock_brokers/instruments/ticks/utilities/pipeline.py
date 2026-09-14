"""
One broker tick in, at most one unified quote and one table row out.

The steps, cheapest refusal first so that ticks which will be dropped cost as little as possible:

1. resolve the tick's token to a compiled plan - one dictionary look-up once the plan exists;
2. drop it if it arrived outside its instrument's session window;
3. ask the ownership engine whether this broker owns the instrument - a backup's tick stops here;
4. normalize the values;
5. set the previous close, from the broker where its `close` means that and otherwise from what this
   instrument's owner reported earlier the same day, and recompute the change from it;
6. drop it if nothing but the clock has changed since the last tick written for the instrument.

The survivor becomes a quote - the JSON the unified cache stores and publishes - and a row for
unified.ticks. The quote splices in the instrument's identity, serialized once when its plan was
compiled, so building one costs a single `json.dumps` of the changing fields.

Nothing here touches Redis or the database: the live service drives this class.
"""

import json
import time
from collections import Counter, namedtuple

from stock_brokers.instruments.ticks.utilities.sessions import SessionGate, india_day_number

# instrument_id: the unified id. quote: the JSON for the unified cache. row: the values for
# unified.ticks in TICK_COLUMNS order, with instants still as epoch seconds. transitions:
# ownership changes this tick caused, which are recorded even when the tick itself is not written.
Output = namedtuple("Output", ["instrument_id", "quote", "row", "transitions"])

TICK_COLUMNS = [
    "time", "instrument_id", "broker", "exchange_time", "last_trade_time",
    "last_price", "last_quantity", "average_price", "volume", "buy_quantity", "sell_quantity",
    "open", "high", "low", "previous_close", "change_percent",
    "oi", "oi_day_high", "oi_day_low", "lot_size",
] + [f"{side}{level}_{field}"
     for side in ("bid", "ask") for level in range(1, 6)
     for field in ("price", "quantity", "orders")]

# Positions in a row of the three instants, which the table writer renders as timestamps.
TIME_COLUMN_POSITIONS = (0, 3, 4)

# A row's values from this position on are what de-duplication compares: everything except the
# receipt time, the id, the broker and the two exchange instants, which move when nothing else does.
_VALUES_FROM = 5

_EMPTY_LEVEL = (None, None, None)
_SEPARATORS = (",", ":")

def change_percent_from(last_price, previous_close):
    """
    The change since the previous close, as a percentage rounded to four places.

    Recomputed rather than taken from the broker, because brokers disagree on what their own change
    field means - Kite's index packets send points where everything else sends a percentage.

    Args:
        last_price (float): The last traded price.
        previous_close (float | None): The previous session's close.

    Returns:
        float | None: The change, or None without a previous close.
    """
    return round((last_price - previous_close) * 100 / previous_close, 4) if previous_close else None

def quote_document(plan, values, previous_close, change_percent, received_at, unified_at):
    """
    The unified quote JSON for one normalized tick.

    The one place the quote's layout is written, so the unified tick service and anything else that
    produces a quote - the REST API's broker fallback - hand out documents of exactly the same shape.

    Args:
        plan (InstrumentPlan): The instrument's compiled plan, whose serialized identity is spliced in.
        values (dict): What the broker's normalizer returned.
        previous_close (float | None): The previous session's close.
        change_percent (float | None): The change since that close.
        received_at (float): When the tick was received, in epoch seconds.
        unified_at (float): When the quote was built, in epoch seconds.

    Returns:
        str: The quote as compact JSON.
    """
    body = {
        "last_price": values["last_price"],
        "average_price": values["average_price"],
        "ohlc": {"open": values["open"], "high": values["high"], "low": values["low"]},
        "previous_close": previous_close,
        "change_percent": change_percent,
        "last_quantity": values["last_quantity"],
        "volume": values["volume"],
        "buy_quantity": values["buy_quantity"],
        "sell_quantity": values["sell_quantity"],
        "oi": values["oi"],
        "oi_day_high": values["oi_day_high"],
        "oi_day_low": values["oi_day_low"],
        "depth": {
            "buy": [{"price": price, "quantity": quantity, "orders": orders} for price, quantity, orders in values["bids"]],
            "sell": [{"price": price, "quantity": quantity, "orders": orders} for price, quantity, orders in values["asks"]],
        },
        "last_trade_time": values["last_trade_time"],
        "exchange_time": values["exchange_time"],
        "received_at": received_at,
        "unified_at": unified_at,
        "stale": False,
        "stale_since": None,
    }
    return "{" + plan.identity_json + "," + json.dumps(body, separators=_SEPARATORS)[1:]

class TickPipeline:
    """
    Turns broker ticks into unified quotes and rows.

    Attributes:
        counts (Counter): How many ticks ended at each step - received, unresolved, out_of_session, not_owner, no_price, duplicate and written.
    """

    def __init__(self, resolver, ownership, normalizers, gate=None, clock=time.time):
        """
        Build the pipeline.

        Args:
            resolver (TickResolver): Resolves tokens to plans.
            ownership (OwnershipEngine): Decides which broker's ticks are written.
            normalizers (dict): Broker name to TickNormalizer.
            gate (SessionGate | None): Session windows, defaulting to one with the standard tables.
            clock (callable): Returns the current epoch, stamped on quotes as unified_at.

        Returns:
            None: This function returns nothing.
        """
        self.resolver = resolver
        self.ownership = ownership
        self._normalizers = normalizers
        self._gate = gate or SessionGate()
        self._clock = clock
        self.counts = Counter()
        self._previous_close = {}
        self._last_values = {}
        self._last_quote = {}

    def process(self, broker, socket, tick):
        """
        Take one tick through every step.

        Args:
            broker (str): The broker whose feed published the tick.
            socket (str): The socket it arrived on.
            tick (dict): The tick as the broker's market feed published it.

        Returns:
            Output | None: The outcome, or None when the tick was dropped without changing ownership.
        """
        counts = self.counts
        counts["received"] += 1
        received_at = tick.get("received_at")
        if received_at is None:
            counts["unresolved"] += 1
            return None

        plan = self.resolver.plan_for(broker, tick.get("instrument_token"), received_at)
        if plan is None:
            counts["unresolved"] += 1
            return None

        gate = self._gate
        session = plan.session
        if not gate.in_window(plan.exchange, session, received_at):
            counts["out_of_session"] += 1
            return None

        instrument_id = plan.instrument_id
        write, transitions = self.ownership.observe(broker, socket, instrument_id, plan.exchange, received_at,
                                                    gate.window_end_epoch(plan.exchange, session, received_at))
        if not write:
            counts["not_owner"] += 1
            return Output(instrument_id, None, None, transitions) if transitions else None

        values = self._normalizers[broker].normalize(tick, plan, gate.before_trading_close(session, received_at))
        if values is None:
            counts["no_price"] += 1
            return Output(instrument_id, None, None, transitions) if transitions else None

        day = india_day_number(received_at)
        previous_close = values["reported_close"]
        if previous_close is not None:
            self._previous_close[instrument_id] = (day, previous_close)
        else:
            known = self._previous_close.get(instrument_id)
            if known is not None and known[0] == day:
                previous_close = known[1]

        last_price = values["last_price"]
        change_percent = change_percent_from(last_price, previous_close)

        bids = values["bids"]
        asks = values["asks"]
        row = [
            received_at, instrument_id, broker, values["exchange_time"], values["last_trade_time"],
            last_price, values["last_quantity"], values["average_price"], values["volume"],
            values["buy_quantity"], values["sell_quantity"],
            values["open"], values["high"], values["low"], previous_close, change_percent,
            values["oi"], values["oi_day_high"], values["oi_day_low"], plan.lot_size,
        ]
        for levels in (bids, asks):
            for index in range(5):
                row.extend(levels[index] if index < len(levels) else _EMPTY_LEVEL)

        comparable = tuple(row[_VALUES_FROM:])
        if not transitions and self._last_values.get(instrument_id) == comparable:
            counts["duplicate"] += 1
            return None
        self._last_values[instrument_id] = comparable

        quote = quote_document(plan, values, previous_close, change_percent, received_at, self._clock())
        self._last_quote[instrument_id] = quote

        counts["written"] += 1
        return Output(instrument_id, quote, row, transitions)

    def stale_quote(self, instrument_id, stale_since):
        """
        The last quote written for an instrument, flagged stale.

        Args:
            instrument_id (str): The instrument id.
            stale_since (float): When its owner went unhealthy with no backup.

        Returns:
            str | None: The quote JSON, or None when nothing has been written for the instrument.
        """
        quote = self._last_quote.get(instrument_id)
        if quote is None:
            return None
        body = json.loads(quote)
        body["stale"] = True
        body["stale_since"] = stale_since
        quote = json.dumps(body, separators=_SEPARATORS)
        self._last_quote[instrument_id] = quote
        return quote

    def seed_previous_close(self, instrument_id, epoch, previous_close):
        """
        Remember an instrument's previous close from before this process started.

        Args:
            instrument_id (str): The instrument id.
            epoch (float): When it was recorded, which decides the day it belongs to.
            previous_close (float): The previous close.

        Returns:
            None: This function returns nothing.
        """
        self._previous_close[instrument_id] = (india_day_number(epoch), previous_close)
