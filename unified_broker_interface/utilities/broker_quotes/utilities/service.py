"""
One instrument's live quote for `/ltp`, `/ohlc` and `/quote`: from the cache when it is good enough, from a
broker when it is not.

**The cache.** Two Redis hashes hold quotes, both in the unified quote document's shape:

- `unified:quotes:live`, written by `bin/unified/instruments/websocket_quotes` from every broker's quote feed, keyed by instrument id;
- `unified:quotes:fetched`, written here with quotes fetched from brokers, each field expiring after two days.

The more recently received of the two is used when it is not marked stale and either:

- it was received in the last five minutes, or
- the instrument's trading window has closed since it was received, and has not reopened.

Most instruments are thinly traded and go long stretches without a trade, so a five minute old quote is
still the market; and once the session is over the last quote stays right until the next one opens, so
nothing is fetched after hours for an instrument that was quoted during the day.

**A broker.** Otherwise the brokers that carry the instrument and have a REST quote module are tried in
the unified tick service's priority order, verified brokers first. The response becomes a contract
tick, is resolved to the instrument's plan and normalized by that broker's `TickNormalizer`, and is
built into a document in the same shape `bin/unified/instruments/websocket_quotes` writes - so a fetched quote and a streamed one are
indistinguishable but for `source`. The fetched quote is stored in `unified:quotes:fetched`, never in
`unified:quotes:live`, whose ownership rules belong to `bin/unified/instruments/websocket_quotes`.
"""

import json
import threading
import time

from stock_brokers.instruments.ticks.utilities.pipeline import change_percent_from, quote_document
from stock_brokers.instruments.ticks.utilities.registry import build_normalizers
from stock_brokers.instruments.ticks.utilities.resolution import CacheCandidateSource, TickResolver
from stock_brokers.instruments.ticks.utilities.sessions import SessionGate, india_day_number, session_for
from stock_brokers.instruments.ticks.utilities.sources import rank
from unified_broker_interface.utilities.broker_quotes.base import QuoteUnavailable
from unified_broker_interface.utilities.broker_quotes.dhan import DhanQuoteSource
from unified_broker_interface.utilities.broker_quotes.flattrade import FlattradeQuoteSource
from unified_broker_interface.utilities.broker_quotes.indmoney import IndmoneyQuoteSource
from unified_broker_interface.utilities.broker_quotes.kotak import KotakQuoteSource
from unified_broker_interface.utilities.broker_quotes.shoonya import ShoonyaQuoteSource
from unified_broker_interface.utilities.broker_quotes.utilities.clients import client_for, relogin, session_marker
from unified_broker_interface.utilities.broker_quotes.zerodha import ZerodhaQuoteSource
from unified_broker_interface.utilities.instrument_identity import RequestError
from utilities.configurations import get_logger

logger = get_logger("rest_api.quotes")

# The live quotes bin/unified/instruments/websocket_quotes keeps, and the quotes fetched from brokers here.
LIVE_QUOTES_KEY = "unified:quotes:live"
BROKER_QUOTES_KEY = "unified:quotes:fetched"

# A cached quote received this recently is used whatever the session is doing.
FRESH_SECONDS = 300

# How long a fetched quote is kept, as a per-field expiry on the hash.
BROKER_QUOTE_TTL_SECONDS = 2 * 86400

# How often the resolver re-reads the mapping date, as the tick service does.
RESOLVER_REFRESH_SECONDS = 30

# Brokers whose REST quote module is in service: each was checked against live quotes and against
# Zerodha on the same instruments. Two modules exist but are held back:
# - fyers: its field mapping is unverified, because every probe met Fyers' request limit, which its candle
#   downloader was using up;
# - groww: the account is not entitled to live data, and every quote request is refused with 403.
SOURCES = {source.BROKER_NAME: source() for source in (ZerodhaQuoteSource, DhanQuoteSource, KotakQuoteSource,
                                                        FlattradeQuoteSource, ShoonyaQuoteSource,
                                                        IndmoneyQuoteSource)}

class QuoteService:
    """
    Serves live quotes from the cache or a broker.

    Attributes:
        mapping_cache (MappingCache): The worker's mapping cache, for broker handles and plans.
        cache (redis.Redis): The shared Redis client, decoding responses.
    """

    def __init__(self, mapping_cache, cache):
        """
        - `mapping_cache` is the worker's `MappingCache`.
        - `cache` is a Redis client with `decode_responses` on.
        """
        self.mapping_cache = mapping_cache
        self.cache = cache
        self._gate = SessionGate()
        self._normalizers = build_normalizers(list(SOURCES))
        self._resolver = TickResolver(CacheCandidateSource(mapping_cache), self._normalizers, logger)
        self._resolver_refreshed_at = 0.0
        self._resolver_lock = threading.Lock()

    def quote(self, identity, mapping_date):
        """
        The instrument's quote document, with `source` saying where it came from.

        - `identity` is the instrument's identity.
        - `mapping_date` is the mapping date the identity was resolved on.
        """
        instrument_id = str(identity["instrument_id"])
        now = time.time()
        cached = self._cached(instrument_id)
        if cached is not None and self._usable(cached, identity, now):
            return {**cached, "source": "cache"}

        handles = self.mapping_cache.order_handles_for_instruments([instrument_id], mapping_date).get(instrument_id, {})
        brokers = sorted((broker for broker in handles if broker in SOURCES),
                         key=lambda broker: rank(broker, identity["exchange"]))
        if not brokers:
            raise RequestError("no recent quote is cached, and no broker that serves quotes carries this instrument", 503)

        failures = []
        for broker in brokers:
            try:
                document = self._from_broker(broker, handles[broker], identity, cached, now)
            except Exception as exception:
                logger.warning(f"{broker} quote for {instrument_id} failed: {type(exception).__name__}: {exception}")
                failures.append(f"{broker}: {str(exception)[:200]}")
                continue
            return {**document, "source": "broker"}
        raise RequestError(f"no recent quote is cached, and every broker failed - {'; '.join(failures)}", 503)

    def _cached(self, instrument_id):
        """
        The more recently received of the live quote and a fetched one, or None.
        """
        pipeline = self.cache.pipeline()
        pipeline.hget(LIVE_QUOTES_KEY, instrument_id)
        pipeline.hget(BROKER_QUOTES_KEY, instrument_id)
        best = None
        for stored in pipeline.execute():
            if not stored:
                continue
            try:
                document = json.loads(stored)
            except ValueError:
                continue
            if best is None or (document.get("received_at") or 0) > (best.get("received_at") or 0):
                best = document
        return best

    def _usable(self, document, identity, now):
        """
        Whether a cached quote may be served instead of asking a broker.
        """
        if document.get("stale"):
            return False
        received_at = document.get("received_at")
        if not received_at:
            return False
        if now - received_at <= FRESH_SECONDS:
            return True
        session = session_for(identity["segment"])
        exchange = identity["exchange"]
        return (self._gate.window_end_epoch(exchange, session, received_at) <= now
                and not self._gate.in_window(exchange, session, now))

    def _from_broker(self, broker, handle, identity, cached, now):
        """
        Fetch, normalize and store one broker's quote for the instrument.
        """
        source = SOURCES[broker]
        client = client_for(broker)
        session = session_marker(client)
        try:
            tick = source.fetch(client, handle, identity, now)
        except QuoteUnavailable:
            raise
        except Exception as exception:
            if not source.is_authentication_error(exception):
                raise
            relogin(broker, client, session)
            tick = source.fetch(client, handle, identity, now)

        with self._resolver_lock:
            if now - self._resolver_refreshed_at >= RESOLVER_REFRESH_SECONDS:
                self._resolver.refresh(now)
                self._resolver_refreshed_at = now
            plan = self._resolver.plan_for(broker, tick["instrument_token"], now)
        if plan is None:
            raise QuoteUnavailable(f"{broker} token {handle['broker_token']} does not resolve to one instrument")
        if plan.instrument_id != str(identity["instrument_id"]):
            raise QuoteUnavailable(f"{broker} token {handle['broker_token']} resolves to {plan.instrument_id}")

        values = self._normalizers[broker].normalize(tick, plan, self._gate.before_trading_close(plan.session, now))
        if values is None:
            raise QuoteUnavailable(f"{broker} returned no usable last price")

        previous_close = values["reported_close"]
        if (previous_close is None and cached is not None and cached.get("received_at")
                and india_day_number(cached["received_at"]) == india_day_number(now)):
            previous_close = cached.get("previous_close")

        document = quote_document(plan, values, previous_close, change_percent_from(values["last_price"], previous_close),
                                  now, time.time())
        pipeline = self.cache.pipeline()
        pipeline.hset(BROKER_QUOTES_KEY, plan.instrument_id, document)
        pipeline.hexpire(BROKER_QUOTES_KEY, BROKER_QUOTE_TTL_SECONDS, plan.instrument_id)
        pipeline.execute()
        return json.loads(document)
