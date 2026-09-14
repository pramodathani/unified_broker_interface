"""
Resolving the tokens on broker ticks to unified instrument ids, and compiling what each needs.

A tick names its instrument in its broker's own spelling. The broker's normalizer turns that into
the token and canonical segments the broker mappings are searched with; this module does
the search, refuses to guess when the answer is not unique, and compiles an `InstrumentPlan` holding
everything the per-tick path needs, so that path is a single dictionary look-up.

`CacheCandidateSource` answers the search, over the three tier mapping cache. It covers the current mapping date
only, which is what a quote needs.

Misses are remembered for ten minutes, so a token nothing maps costs one search per ten minutes
rather than one per tick, and a token mapped by the morning's download is picked up soon after.
"""

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

from sqlalchemy import text

from stock_brokers.instruments.mapping.utilities import tables
from stock_brokers.instruments.ticks.base import (BASIS_BROKER_LOTS, BASIS_LOTS, QUANTITY_FIELDS, InstrumentPlan,
                                                  identity_json)
from stock_brokers.instruments.ticks.utilities.sessions import india_date, session_for

# How long a token that did not resolve is left alone before it is searched for again.
MISS_RETRY_SECONDS = 600.0

# The broker whose lot sizes are the authority on MCX. The brokers disagree - on 2026-09-13 GOLD OCT
# had a lot of 100 at Groww only and 1 at the other eight, CRUDEOIL SEP 100 at five and 1 at four -
# and only Groww's makes price times quantity the contract's notional value in every case sampled.
MCX_LOT_AUTHORITY = "groww"


def order_symbol_index(engine, broker, mapping_date):
    """
    A broker's order symbol to broker token dictionary, for one mapping date.

    The mapping cache is keyed by token, but a Fyers tick names its instrument by symbol, and the
    symbol is what the broker mappings store as the order symbol. One query per mapping date
    - about 160,000 rows for Fyers - builds the translation.

    Args:
        engine (sqlalchemy.engine.Engine): An engine over TimescaleDB.
        broker (str): The broker.
        mapping_date (datetime.date): The mapping date.

    Returns:
        dict: Order symbol to broker token. A symbol listed twice keeps its first token.
    """
    index = {}
    with engine.connect() as connection:
        statement = text(f"SELECT order_symbol, broker_token FROM {tables.BROKER_MAPPINGS} "
                         "WHERE broker = :broker AND mapping_date = :mapping_date AND order_symbol IS NOT NULL")
        for order_symbol, broker_token in connection.execute(statement, {"broker": broker, "mapping_date": mapping_date}):
            index.setdefault(order_symbol, broker_token)
    return index

class CacheCandidateSource:
    """
    Candidates from the three tier mapping cache, for the current mapping date.

    Attributes:
        mapping_cache (MappingCache): The process's mapping cache.
    """

    def __init__(self, mapping_cache):
        """
        Wrap a mapping cache.

        Args:
            mapping_cache (MappingCache): The process's mapping cache, shared with anything else in the process that resolves instruments.

        Returns:
            None: This function returns nothing.
        """
        self.mapping_cache = mapping_cache

    def order_symbols(self, broker, as_of_date):
        """
        A broker's order symbol to token dictionary for the current mapping date.

        Args:
            broker (str): The broker.
            as_of_date (datetime.date): The India trading day.

        Returns:
            dict: Order symbol to broker token.
        """
        mapping_date = self.mapping_date(as_of_date)
        return order_symbol_index(self.mapping_cache.engine, broker, mapping_date) if mapping_date else {}

    def mapping_date(self, as_of_date):
        """
        The mapping date that answers for a day.

        Args:
            as_of_date (datetime.date): The India trading day the ticks belong to.

        Returns:
            datetime.date | None: The current mapping date, or None when the cache cannot answer for that day.
        """
        return self.mapping_cache.resolves_to_current_date(as_of_date)

    def candidates(self, broker, broker_tokens, as_of_date, segments):
        """
        Every identity each token maps to inside the segments.

        Args:
            broker (str): The broker name.
            broker_tokens (list[str]): Tokens as stored in unified.broker_mappings.
            as_of_date (datetime.date): The India trading day.
            segments (tuple[str]): Canonical segments to search.

        Returns:
            dict: Token to a list of identity dicts.
        """
        return self.mapping_cache.candidates_for_tokens(broker, broker_tokens, as_of_date, list(segments))

    def handles(self, instrument_ids, as_of_date):
        """
        Every broker's order handle - token, symbol, lot size, tick size - for each instrument.

        Args:
            instrument_ids (list[str]): Instrument ids.
            as_of_date (datetime.date): The India trading day.

        Returns:
            dict: Instrument id to broker name to handle dict.
        """
        return self.mapping_cache.order_handles_for_instruments(instrument_ids, as_of_date)

def _whole_number(value):
    """A lot size as a positive int, or None."""
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if number <= 0 or number != number.to_integral_value():
        return None
    return int(number)

def units_per_lot(identity, handles_by_broker):
    """
    How many underlying units one lot of an instrument is.

    Args:
        identity (dict): The instrument's identity.
        handles_by_broker (dict): Broker name to that broker's handle for the instrument.

    Returns:
        tuple[int | None, str | None]: The units per lot, or None when it cannot be decided, and a note when the brokers disagreed or the authority was missing.
    """
    if identity.get("shape") == "security":
        return 1, None

    if identity.get("exchange") == "mcx":
        handle = handles_by_broker.get(MCX_LOT_AUTHORITY)
        size = _whole_number(handle.get("lot_size")) if handle else None
        if size is None:
            return None, f"no {MCX_LOT_AUTHORITY} lot size"
        return size, None

    sizes = Counter()
    for handle in handles_by_broker.values():
        size = _whole_number(handle.get("lot_size"))
        if size is not None:
            sizes[size] += 1
    if not sizes:
        return None, "no broker lot size"
    ranked = sizes.most_common()
    note = None
    if len(ranked) > 1:
        note = "brokers disagree: " + ", ".join(f"{size}x{count}" for size, count in ranked)
        if ranked[0][1] == ranked[1][1]:
            return None, note
    return ranked[0][0], note

def _expired(identity, as_of_date):
    """Whether a derivative had expired before a day, which rules it out as a live candidate."""
    expiry = identity.get("expiry_date")
    if not expiry:
        return False
    return str(expiry)[:10] < as_of_date.isoformat()

class TickResolver:
    """
    Instrument plans for broker tokens, compiled once per token per mapping date.

    Attributes:
        unresolved (Counter): (broker, token, reason) to ticks that could not be resolved since last drained, where reason is one of no_normalizer, unplaceable, unmapped, ambiguous or no_mapping_date.
        notes (dict): (broker, token) to a note about a compiled plan, such as a lot size disagreement.
        as_of_date (datetime.date | None): The India trading day plans are compiled for.
        mapping_date (datetime.date | None): The mapping date plans are compiled from.
    """

    def __init__(self, source, normalizers, logger=None):
        """
        Build the resolver.

        Args:
            source (CacheCandidateSource): Where candidates come from.
            normalizers (dict): Broker name to TickNormalizer.
            logger (logging.Logger | None): Where decisions worth knowing are reported.

        Returns:
            None: This function returns nothing.
        """
        self._source = source
        self._normalizers = normalizers
        self._logger = logger
        self._plans = {}
        self._order_symbols = {}
        self.unresolved = Counter()
        self.notes = {}
        self.as_of_date = None
        self.mapping_date = None
        self._logged = set()

    def refresh(self, epoch):
        """
        Move to the India trading day an instant falls on, dropping every plan if the mapping changed.

        The live service calls this every thirty seconds with the wall clock.

        Args:
            epoch (float): An instant on the day to resolve for.

        Returns:
            bool: True when the plans were dropped because the day's mapping date differs from theirs.
        """
        # The mapping date is asked for on every call, not only when the day changes: the morning's
        # download moves it at 07:45, hours after midnight moved the day, and a resolver that checked
        # only at midnight would serve the previous day's plans until the next one.
        as_of_date = india_date(epoch)
        mapping_date = self._source.mapping_date(as_of_date)
        self.as_of_date = as_of_date
        if mapping_date == self.mapping_date:
            return False
        dropped = bool(self._plans)
        self._plans = {}
        self._order_symbols = {}
        self.notes = {}
        self._logged = set()
        self.mapping_date = mapping_date
        if dropped and self._logger:
            self._logger.info(f"Mapping date is now {mapping_date}; instrument plans will be recompiled.")
        return dropped

    def plan_for(self, broker, instrument_token, now):
        """
        The plan for a tick's token, compiling it on first sight.

        Args:
            broker (str): The broker the tick came from.
            instrument_token (int | str): The tick's `instrument_token`.
            now (float): The current instant, used to decide when a miss may be retried.

        Returns:
            InstrumentPlan | None: The plan, or None when the token does not resolve to one instrument.
        """
        key = (broker, instrument_token)
        plan = self._plans.get(key)
        if plan is not None:
            if plan.__class__ is InstrumentPlan:
                return plan
            if now < plan:
                return None
        return self.compile(broker, [instrument_token], now).get(key)

    def prewarm(self, broker, subscription_tokens, now):
        """
        Compile plans for every token a broker's feed is subscribed to, before its ticks arrive.

        This is what keeps the mapping search off the per-tick path: by the time a subscribed
        instrument's first tick arrives its plan is already filed under the tick's spelling.

        Args:
            broker (str): The broker name.
            subscription_tokens (list[str]): Members of the broker's subscription set.
            now (float): The current instant.

        Returns:
            tuple[int, int]: How many of the tokens have a plan, and how many there were.
        """
        normalizer = self._normalizers.get(broker)
        if normalizer is None:
            return 0, len(subscription_tokens)
        spellings = []
        for token in subscription_tokens:
            spelling = normalizer.tick_spelling(token)
            if spelling is None:
                self._miss(broker, token, "unplaceable", now + MISS_RETRY_SECONDS)
            else:
                spellings.append(spelling)
        missing = [spelling for spelling in spellings if (broker, spelling) not in self._plans]
        if missing:
            self.compile(broker, missing, now)
        planned = sum(1 for spelling in spellings if self._plans.get((broker, spelling)).__class__ is InstrumentPlan)
        return planned, len(subscription_tokens)

    def compile(self, broker, instrument_tokens, now):
        """
        Resolve a batch of one broker's tokens and compile their plans.

        Args:
            broker (str): The broker name.
            instrument_tokens (list): Tokens spelled as they appear on ticks.
            now (float): The current instant.

        Returns:
            dict: (broker, token) to InstrumentPlan, for the tokens that resolved.
        """
        if self.as_of_date is None:
            self.refresh(now)
        retry_at = now + MISS_RETRY_SECONDS
        normalizer = self._normalizers.get(broker)
        if normalizer is None:
            for token in instrument_tokens:
                self._miss(broker, token, "no_normalizer", retry_at)
            return {}
        if self.mapping_date is None:
            for token in instrument_tokens:
                self._miss(broker, token, "no_mapping_date", retry_at)
            return {}

        groups = defaultdict(list)
        for token in instrument_tokens:
            feed_key = normalizer.feed_key(token)
            if feed_key is None:
                self._miss(broker, token, "unplaceable", retry_at)
                continue
            broker_token = feed_key.broker_token
            if broker_token is None and feed_key.order_symbol is not None:
                if broker not in self._order_symbols:
                    self._order_symbols[broker] = self._source.order_symbols(broker, self.as_of_date)
                broker_token = self._order_symbols[broker].get(feed_key.order_symbol)
            if broker_token is None:
                self._miss(broker, token, "unmapped", retry_at)
                continue
            groups[feed_key.segments].append((token, broker_token))

        chosen = {}
        for segments, items in groups.items():
            found = self._source.candidates(broker, sorted({broker_token for _, broker_token in items}),
                                            self.as_of_date, segments)
            for token, broker_token in items:
                candidates = [identity for identity in found.get(broker_token, ())
                              if not _expired(identity, self.as_of_date)]
                distinct = {identity["instrument_id"] for identity in candidates}
                if not distinct:
                    self._miss(broker, token, "unmapped", retry_at)
                elif len(distinct) > 1:
                    self._miss(broker, token, "ambiguous", retry_at,
                               ", ".join(sorted(f"{c['segment']}:{c.get('symbol') or c.get('underlying_symbol')}"
                                                for c in candidates)))
                else:
                    chosen[token] = (broker_token, candidates[0])

        if not chosen:
            return {}

        handles = self._source.handles(sorted({identity["instrument_id"] for _, identity in chosen.values()}),
                                       self.as_of_date)
        compiled = {}
        for token, (broker_token, identity) in chosen.items():
            plan = self._compile_plan(normalizer, broker, token, broker_token, identity,
                                      handles.get(identity["instrument_id"], {}))
            self._plans[(broker, token)] = plan
            compiled[(broker, token)] = plan
        return compiled

    def drain_unresolved(self):
        """
        Take the unresolved counts accumulated since the last call.

        Returns:
            Counter: (broker, token, reason) to count.
        """
        counts, self.unresolved = self.unresolved, Counter()
        return counts

    def plans(self):
        """
        Every compiled plan, by (broker, token).

        Returns:
            dict: The plans; misses are left out.
        """
        return {key: plan for key, plan in self._plans.items() if plan.__class__ is InstrumentPlan}

    def _compile_plan(self, normalizer, broker, token, broker_token, identity, handles_by_broker):
        exchange = identity["exchange"]
        segment = identity["segment"]
        shape = identity["shape"]
        lot_size, note = units_per_lot(identity, handles_by_broker)
        if note:
            self.notes[(broker, token)] = note
            self._log_once(("lot", broker, token), f"{broker} {token} ({segment}): lot size {lot_size} - {note}.")

        broker_lot = _whole_number((handles_by_broker.get(broker) or {}).get("lot_size"))
        multipliers = {}
        for field in QUANTITY_FIELDS:
            basis = normalizer.quantity_basis(exchange, field)
            if basis == BASIS_LOTS:
                multipliers[field] = lot_size
            elif basis == BASIS_BROKER_LOTS:
                if lot_size is None or broker_lot is None:
                    multipliers[field] = None
                elif lot_size % broker_lot == 0:
                    multipliers[field] = lot_size // broker_lot
                else:
                    multipliers[field] = lot_size / broker_lot
            else:
                multipliers[field] = 1

        return InstrumentPlan(
            instrument_id=identity["instrument_id"],
            broker=broker,
            broker_token=broker_token,
            exchange=exchange,
            segment=segment,
            shape=shape,
            session=session_for(segment),
            lot_size=lot_size,
            multipliers=multipliers,
            price_decimals=4 if "_currenc" in segment else 2,
            negative_prices=shape != "security" and exchange in ("mcx", "ncdex"),
            close_policy=normalizer.close_policy(exchange),
            has_open_interest=shape != "security",
            trusts_last_trade_time=normalizer.TRUSTS_LAST_TRADE_TIME,
            trusts_exchange_time=normalizer.TRUSTS_EXCHANGE_TIME,
            identity_json=identity_json(identity["instrument_id"], broker, broker_token, identity, lot_size),
        )

    def _miss(self, broker, token, reason, retry_at, detail=None):
        self._plans[(broker, token)] = retry_at
        self.unresolved[(broker, str(token), reason)] += 1
        message = f"{broker} token {token} did not resolve: {reason}"
        self._log_once((broker, token, reason), message + (f" ({detail})." if detail else "."))

    def _log_once(self, key, message):
        if key in self._logged or self._logger is None:
            return
        self._logged.add(key)
        self._logger.warning(message)
