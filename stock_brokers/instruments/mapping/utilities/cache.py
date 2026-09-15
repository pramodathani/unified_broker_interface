"""
A three tier cache in front of the mapped instrument tables.

Instrument resolution is moving into the hot paths. The portfolio construction models resolve every holding and position on every refresh, and the execution models resolve an instrument on every order, so a database round trip in that path is the thing to remove. Measured on this machine, a process dictionary answers in 0.18 microseconds, a pipelined Redis read in 3.3, and a Postgres resolution in about a thousand. The read order follows that ordering exactly: this process's own memory, then Redis, then Postgres, with each tier filling in the ones above it on a miss.

Postgres remains the system of record. Nothing here holds anything that cannot be rebuilt from it, so flushing Redis costs one query per instrument actually touched and nothing else, and an unreachable Redis is a miss rather than an error.

Only the current mapping date is cached. A question about a past date goes straight to the existing queries in resolution.py and caches nothing, because a backtest asking about March is not a hot path and caching every historical date would multiply the memory for no benefit.

Five classes divide the work. ``MappingRedisTier`` owns the three Redis hashes, both reading and writing every one of them, so the shape written and the shape read cannot drift apart. ``MappingPostgresTier`` owns every statement, so the tie-break ordering that the cached answer and the database answer must share is written once. ``ThreeTierLookup`` holds the walk from one tier to the next, and its three subclasses supply the reads and writes for the three questions that get asked. ``MappingCache`` is what a caller holds, and it owns the engine so that no method needs one passed to it.
"""

import datetime
import decimal
import json
import time
import uuid

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from sqlalchemy import text

from stock_brokers.instruments.mapping.utilities import tables
from utilities.configurations import get_postgres_engine, redis_configuration

CURRENT_DATE_REFRESH_SECONDS = 300.0
READ_BATCH_TOKENS = 5000

DATE_FIELDS = (
    "expiry_date",
    "mapping_date",
)
DECIMAL_FIELDS = (
    "strike_price",
)


def as_text(value):
    """
    Decode one value Redis returned, which is bytes unless the client was built to decode responses.

    Args:
        value (bytes | str | None): The value as Redis returned it.

    Returns:
        str | None: The value as text, or None when there was none.
    """
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode()
    return value


class MappingRedisConnection:
    """
    One lazily opened Redis client for the mapping cache, which reports unavailability rather than raising.

    Redis here sits in front of data Postgres still holds, so an unreachable Redis has to degrade
    into a cache miss rather than into an error on an order being placed. A caller asks for the
    client on every use and checks the answer for None, rather than holding it, so a Redis that
    went away between two look-ups is noticed at the second.

    This does not use `get_cache` from `utilities.configurations`, and the difference is deliberate
    rather than an oversight. That client is built for long lived connections: it has no
    `socket_timeout`, so a blocking read can sit through an idle period without raising, and it
    leaves redis-py's default retry in place. Both are right for a connection held silent overnight
    and wrong here, where a refused port would take about six seconds to be declared refused and the
    six seconds would land on whichever look-up happened to be first. Disabling the retry and
    setting both timeouts explicitly reaches the same conclusion in under a millisecond. The
    address still comes from `redis_configuration`, so there remains one source of truth for where
    Redis is; only how this client waits on it differs.

    Attributes:
        RETRY_SECONDS (float): How long a failed connection is remembered before another attempt.
        CONNECT_TIMEOUT_SECONDS (float): How long one connection attempt may take.
        SOCKET_TIMEOUT_SECONDS (float): How long one command may take once connected.
        failed_connections (int): Attempts that did not succeed, counted so a Redis nobody can
            reach is visible rather than silent.
    """

    RETRY_SECONDS = 60.0
    CONNECT_TIMEOUT_SECONDS = 0.5
    SOCKET_TIMEOUT_SECONDS = 1.0

    def __init__(self, client=None):
        """
        Build the connection, optionally around a client the caller already has.

        Args:
            client (redis.Redis | None): An already connected client, which is how a test or a
                caller with its own pool supplies one. None opens a client on first use.

        Returns:
            None: This method returns nothing.
        """
        self.failed_connections = 0
        self._client = client
        self._unavailable_until = 0.0

    def client(self):
        """
        The connected Redis client, or None when Redis cannot be reached right now.

        Returns:
            redis.Redis | None: A connected client, or None when Redis could not be reached and the
                retry window has not yet passed.
        """
        if self._client is not None:
            return self._client
        if time.monotonic() < self._unavailable_until:
            return None
        try:
            client = redis.Redis(
                host=redis_configuration["host"],
                port=redis_configuration["port"],
                db=redis_configuration["db"],
                username=redis_configuration["username"],
                password=redis_configuration["password"],
                socket_connect_timeout=self.CONNECT_TIMEOUT_SECONDS,
                socket_timeout=self.SOCKET_TIMEOUT_SECONDS,
                retry=Retry(NoBackoff(), 0),
            )
            client.ping()
        except redis.RedisError:
            self.failed_connections += 1
            self._unavailable_until = time.monotonic() + self.RETRY_SECONDS
            return None
        self._client = client
        return self._client

    def forget(self):
        """
        Drop the client after a failure, so the next look-up reconnects rather than reusing a broken socket.

        Returns:
            None: This method returns nothing.
        """
        self._client = None
        self._unavailable_until = time.monotonic() + self.RETRY_SECONDS


class MappingRedisTier:
    """
    Reads and writes the three Redis hashes that hold one day's instrument mapping.

    Every read and every write of these hashes goes through this class, including the daily warm's. That is the whole point of it. If the reader and the warm each encoded the instrument-keyed entry, a four field order handle, on their own, a change made to one and not the other would leave Redis holding a shape that decodes successfully into something the caller cannot use. With one class owning both directions there is nowhere for the two shapes to disagree.

    Attributes:
        KEY_PREFIX (str): The prefix every key in this cache shares, `tables.MAPPING_CACHE_PREFIX`: `unified:catalogue:`.
        connection (MappingRedisConnection): The connection the hashes are read and written through.
    """

    def __init__(self, connection=None):
        """
        Build the tier around a Redis connection.

        Args:
            connection (MappingRedisConnection | None): The connection to use. None builds one.

        Returns:
            None: This function returns nothing.
        """
        self.connection = connection or MappingRedisConnection()
        self.KEY_PREFIX = tables.MAPPING_CACHE_PREFIX

    def current_date_key(self):
        """
        The key holding the latest warmed mapping date.

        Returns:
            str: The full key.
        """
        return f"{self.KEY_PREFIX}current_date"

    def warm_identifier_key(self):
        """
        The key holding an identifier that changes on every warm, even one that re-warms the same date.

        A process that keeps catalogue data in its own memory compares this with the identifier it read the data under, because the mapping date alone does not change when a warm is re-run for the same date.

        Returns:
            str: The full key.
        """
        return f"{self.KEY_PREFIX}warm_identifier"

    def identity_key(self, mapping_date):
        """
        The key of the hash holding one date's identities, keyed by instrument id.

        Args:
            mapping_date (datetime.date): The mapping date the hash covers.

        Returns:
            str: The full key.
        """
        return f"{self.KEY_PREFIX}{mapping_date.isoformat()}:identity"

    def tokens_key(self, mapping_date, broker):
        """
        The key of the hash holding one broker's tokens for one date, keyed by broker token.

        Args:
            mapping_date (datetime.date): The mapping date the hash covers.
            broker (str): The broker name, for example "zerodha".

        Returns:
            str: The full key.
        """
        return f"{self.KEY_PREFIX}{mapping_date.isoformat()}:tokens:{broker}"

    def order_handles_key(self, mapping_date):
        """
        The key of the hash holding one date's order handles, keyed by instrument id.

        The key says "order_handles" rather than "brokers" because the value stored under it widened from a bare token to the whole handle an order needs. A key of its own means a Redis still holding the narrower value is a miss rather than a decode that succeeds into the wrong shape.

        Args:
            mapping_date (datetime.date): The mapping date the hash covers.

        Returns:
            str: The full key.
        """
        return f"{self.KEY_PREFIX}{mapping_date.isoformat()}:order_handles"

    def segments_key(self, mapping_date):
        """
        The key of the hash holding how many instruments each segment has on one date.

        It is also what says a date's catalogue is complete: the warm writes it after every catalogue and names set, so a reader that finds it can trust the rest.

        Args:
            mapping_date (datetime.date): The mapping date the hash covers.

        Returns:
            str: The full key.
        """
        return f"{self.KEY_PREFIX}{mapping_date.isoformat()}:segments"

    def catalogue_key(self, mapping_date, segment):
        """
        The key of the sorted set listing one segment's instruments on one date, in name order.

        Args:
            mapping_date (datetime.date): The mapping date the set covers.
            segment (str): The exchange-prefixed segment, for example "nse_equities".

        Returns:
            str: The full key.
        """
        return f"{self.KEY_PREFIX}{mapping_date.isoformat()}:catalogue:{segment}"

    def names_key(self, mapping_date, segment):
        """
        The key of the sorted set listing one segment's distinct names on one date.

        A name is a security's symbol or a derivative's underlying. An option segment has hundreds of thousands of contracts but only a few hundred underlyings, so a search scans this set rather than the catalogue.

        Args:
            mapping_date (datetime.date): The mapping date the set covers.
            segment (str): The exchange-prefixed segment, for example "nse_equity_options".

        Returns:
            str: The full key.
        """
        return f"{self.KEY_PREFIX}{mapping_date.isoformat()}:names:{segment}"

    def seen_key(self, mapping_date):
        """
        The key of the hash holding each instrument's first and last seen dates, keyed by instrument id.

        Args:
            mapping_date (datetime.date): The mapping date the hash covers.

        Returns:
            str: The full key.
        """
        return f"{self.KEY_PREFIX}{mapping_date.isoformat()}:seen"

    def catalogue_name(self, identity):
        """
        The name an instrument is listed and searched under: its symbol, or its underlying for a derivative.

        Args:
            identity (dict): The instrument's identity.

        Returns:
            str: The name, upper-cased, with any "|" replaced so it cannot break the member layout.
        """
        name = identity["symbol"] if identity["shape"] == "security" else identity["underlying_symbol"]
        return (name or "").upper().replace("|", "/")

    def encode_catalogue_member(self, identity):
        """
        Encode one instrument as its member of a segment's catalogue set.

        Every member has the score zero, so the set orders lexically, and the member is laid out as ``NAME|expiry|strike|option_type|instrument_id`` so that lexical order is name, then expiry, then strike, then option type. The strike is zero-padded to a fixed width for the same reason: ``"00000000900.0000"`` sorts before ``"00000001000.0000"`` where ``"900"`` would sort after ``"1000"``.

        Args:
            identity (dict): The instrument's identity.

        Returns:
            str: The member.
        """
        expiry = identity["expiry_date"]
        strike = identity["strike_price"]
        return "|".join((
            self.catalogue_name(identity),
            expiry.isoformat() if expiry else "",
            self._catalogue_strike(strike) if strike is not None else "",
            identity["option_type"] or "",
            identity["instrument_id"],
        ))

    def _catalogue_strike(self, strike_price):
        """
        A strike as the catalogue spells it: zero-padded to a fixed width so lexical order is numeric order.

        Args:
            strike_price (decimal.Decimal | int | str): The strike.

        Returns:
            str: The strike, for example "00000025000.0000".
        """
        return f"{decimal.Decimal(strike_price):016.4f}"

    def catalogue_prefix(self, name, expiry_date=None, strike_price=None, option_type=None):
        """
        The start shared by the catalogue members under a name, narrowed by as many identity fields as are given.

        The prefix stops after the first field not given, each part ending in "|": a name alone gives ``NIFTY|``, which every contract under NIFTY shares and no contract under NIFTYNXT50 does; a name and an expiry give the futures and options of that expiry; a whole option identity gives exactly one member. A security's member has nothing after its name, so its name alone finds it.

        Args:
            name (str): The upper-cased name.
            expiry_date (datetime.date | None): The expiry, for a derivative.
            strike_price (decimal.Decimal | None): The strike, for an option.
            option_type (str | None): "CE" or "PE", for an option.

        Returns:
            str: The prefix, ending in "|".
        """
        parts = [name]
        for value in (expiry_date.isoformat() if expiry_date else None,
                      self._catalogue_strike(strike_price) if strike_price is not None else None,
                      option_type or None):
            if value is None:
                break
            parts.append(value)
        return "|".join(parts) + "|"

    def decode_catalogue_member(self, member):
        """
        The instrument id at the end of a catalogue member.

        Args:
            member (bytes | str): The member as Redis returned it.

        Returns:
            str: The instrument id.
        """
        return as_text(member).rsplit("|", 1)[1]

    def read_segment_counts(self, mapping_date):
        """
        How many instruments each segment has on a date, which is also the test for a complete catalogue.

        Args:
            mapping_date (datetime.date): The mapping date to read.

        Returns:
            dict | None: Mapping of segment to instrument count, or None when Redis is unreachable or the date's catalogue has not been warmed.
        """
        client = self.connection.client()
        if client is None:
            return None
        try:
            stored = client.hgetall(self.segments_key(mapping_date))
        except redis.RedisError:
            return None
        if not stored:
            return None
        counts = {}
        for segment, count in stored.items():
            counts[as_text(segment)] = int(as_text(count))
        return counts

    def read_catalogue(self, mapping_date, segment, start, stop):
        """
        One slice of a segment's catalogue, as instrument ids in name order.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            segment (str): The exchange-prefixed segment.
            start (int): The first position to read.
            stop (int): The last position to read, inclusive.

        Returns:
            list[str] | None: The instrument ids, or None when Redis is not usable.
        """
        client = self.connection.client()
        if client is None:
            return None
        try:
            members = client.zrange(self.catalogue_key(mapping_date, segment), start, stop)
        except redis.RedisError:
            return None
        return [self.decode_catalogue_member(member) for member in members]

    def read_catalogue_for_prefix(self, mapping_date, segment, prefix, limit):
        """
        The instruments whose catalogue members start with a prefix, in expiry, strike and option type order.

        A prefix from catalogue_prefix with only a name lists every contract under that name; with a whole identity it finds that one instrument.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            segment (str): The exchange-prefixed segment.
            prefix (str): The member prefix, ending in "|".
            limit (int): The most instrument ids to return.

        Returns:
            list[str] | None: The instrument ids, or None when Redis is not usable.
        """
        client = self.connection.client()
        if client is None:
            return None
        prefix = prefix.encode()
        try:
            members = client.zrangebylex(self.catalogue_key(mapping_date, segment),
                                         b"[" + prefix, b"(" + prefix + b"\xff", start=0, num=limit)
        except redis.RedisError:
            return None
        return [self.decode_catalogue_member(member) for member in members]

    def read_names(self, mapping_date, segment):
        """
        Every distinct name in a segment's catalogue, in lexical order.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            segment (str): The exchange-prefixed segment.

        Returns:
            list[str] | None: The names, or None when Redis is not usable.
        """
        client = self.connection.client()
        if client is None:
            return None
        try:
            names = client.zrange(self.names_key(mapping_date, segment), 0, -1)
        except redis.RedisError:
            return None
        return [as_text(name) for name in names]

    def read_seen(self, mapping_date, instrument_identifiers):
        """
        Instruments' first and last seen dates.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            instrument_identifiers (list[str]): The instrument ids to read.

        Returns:
            dict: Mapping of instrument id to a (first_seen_date, last_seen_date) pair of dates. Instruments Redis did not hold are absent.
        """
        client = self.connection.client()
        if client is None or not instrument_identifiers:
            return {}
        try:
            stored = client.hmget(self.seen_key(mapping_date), instrument_identifiers)
        except redis.RedisError:
            return {}
        seen = {}
        for position, instrument_identifier in enumerate(instrument_identifiers):
            value = as_text(stored[position])
            if value:
                first, last = value.split("|")
                seen[instrument_identifier] = (datetime.date.fromisoformat(first), datetime.date.fromisoformat(last))
        return seen

    def encode_seen(self, first_seen_date, last_seen_date):
        """
        Encode an instrument's first and last seen dates as the text the seen hash stores.

        Args:
            first_seen_date (datetime.date): The first date the instrument was mapped.
            last_seen_date (datetime.date): The last date the instrument was mapped.

        Returns:
            str: The two dates, ``YYYY-MM-DD|YYYY-MM-DD``.
        """
        return f"{first_seen_date.isoformat()}|{last_seen_date.isoformat()}"

    def write_members(self, members_by_key, expiry_seconds):
        """
        Add one batch of members to several lexically ordered sorted sets and set them to expire.

        Args:
            members_by_key (dict): Mapping of sorted set key to the members to add to it, all with score zero.
            expiry_seconds (int): How long each set may live.

        Returns:
            int: The number of members sent, which is zero when there were none or when Redis was not usable.
        """
        client = self.connection.client()
        if client is None:
            return 0
        sent = 0
        try:
            pipeline = client.pipeline()
            for key, members in members_by_key.items():
                if not members:
                    continue
                pipeline.zadd(key, dict.fromkeys(members, 0))
                pipeline.expire(key, expiry_seconds)
                sent += len(members)
            pipeline.execute()
        except redis.RedisError:
            return 0
        return sent

    def seconds_until_midnight(self):
        """
        How long a dated key may live before the calendar day changes under it.

        A mapping is superseded the next morning rather than at midnight, so this is an upper bound rather than a true expiry. It exists so that a Redis nobody tends cannot accumulate a month of stale mappings; the mapping date in every key is what actually enforces freshness.

        Returns:
            int: Seconds remaining until midnight, never less than sixty.
        """
        now = datetime.datetime.now()
        midnight = datetime.datetime.combine(now.date() + datetime.timedelta(days=1), datetime.time.min)
        return max(60, int((midnight - now).total_seconds()))

    def encode_identity(self, identity):
        """
        Encode one identity dictionary as the JSON text Redis stores.

        Args:
            identity (dict): The ten identity fields a resolution returns.

        Returns:
            str: The identity as JSON, with dates as ISO text and the strike price as a decimal string.
        """
        encodable = {}
        for field_name, value in identity.items():
            if value is None:
                encodable[field_name] = None
            elif isinstance(value, datetime.date):
                encodable[field_name] = value.isoformat()
            else:
                encodable[field_name] = str(value)
        return json.dumps(encodable)

    def decode_identity(self, encoded):
        """
        Decode one identity dictionary out of the JSON text Redis stores.

        Args:
            encoded (bytes | str): The JSON text written by encode_identity.

        Returns:
            dict | None: The identity with its dates and its strike price converted back, or None when the text is not a usable identity.
        """
        try:
            identity = json.loads(encoded)
        except (ValueError, TypeError):
            return None
        if not isinstance(identity, dict):
            return None

        for field_name in DATE_FIELDS:
            value = identity.get(field_name)
            if value:
                identity[field_name] = datetime.date.fromisoformat(value)
        for field_name in DECIMAL_FIELDS:
            value = identity.get(field_name)
            if value:
                identity[field_name] = decimal.Decimal(value)
        return identity

    def encode_order_handles(self, handles_by_broker):
        """
        Encode one instrument's order handles as the JSON text Redis stores.

        Args:
            handles_by_broker (dict): Mapping of broker name to that broker's handle, itself a dict with keys "broker_token", "order_symbol", "lot_size" and "tick_size".

        Returns:
            str: The handles as JSON.
        """
        return json.dumps(handles_by_broker)

    def decode_order_handles(self, encoded):
        """
        Decode one instrument's order handles out of the JSON text Redis stores.

        A value that is not a dictionary of dictionaries is rejected rather than returned, so that a Redis left holding an older and narrower shape reads as a miss and is refilled from Postgres.

        Args:
            encoded (bytes | str): The JSON text written by encode_order_handles.

        Returns:
            dict | None: Mapping of broker name to that broker's handle, or None when the text is not a usable set of handles.
        """
        try:
            handles_by_broker = json.loads(encoded)
        except (ValueError, TypeError):
            return None
        if not isinstance(handles_by_broker, dict):
            return None
        for handle in handles_by_broker.values():
            if not isinstance(handle, dict):
                return None
        return handles_by_broker

    def read_current_date(self):
        """
        The latest warmed mapping date, as Redis holds it.

        Returns:
            datetime.date | None: The date, or None when Redis is unreachable or has never been warmed.
        """
        client = self.connection.client()
        if client is None:
            return None
        try:
            stored = as_text(client.get(self.current_date_key()))
        except redis.RedisError:
            return None
        if not stored:
            return None
        return datetime.date.fromisoformat(stored)

    def write_current_date(self, mapping_date):
        """
        Publish the mapping date the hashes now cover, together with a new warm identifier.

        This is written last by a warm, so that a reader sees either the previous complete day or the new complete day and never a half written one. The date and the identifier are set in one transaction, so a reader never sees a new date beside the previous warm's identifier.

        Args:
            mapping_date (datetime.date): The date to publish.

        Returns:
            bool: True when the write went through, False when Redis was not usable.
        """
        client = self.connection.client()
        if client is None:
            return False
        try:
            pipeline = client.pipeline(transaction=True)
            pipeline.set(self.current_date_key(), mapping_date.isoformat())
            pipeline.set(self.warm_identifier_key(), uuid.uuid4().hex)
            pipeline.execute()
        except redis.RedisError:
            return False
        return True

    def read_identities(self, mapping_date, instrument_identifiers):
        """
        Read instruments' identities out of the identity hash.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            instrument_identifiers (list[str]): The instrument ids to read.

        Returns:
            dict: Mapping of instrument id to its identity dict. Instruments Redis did not hold are absent.
        """
        client = self.connection.client()
        if client is None:
            return {}
        if not instrument_identifiers:
            return {}

        try:
            stored = client.hmget(self.identity_key(mapping_date), instrument_identifiers)
        except redis.RedisError:
            return {}

        identities = {}
        for position, instrument_identifier in enumerate(instrument_identifiers):
            if stored[position] is None:
                continue
            identity = self.decode_identity(stored[position])
            if identity is not None:
                identities[instrument_identifier] = identity
        return identities

    def write_identities(self, mapping_date, identities):
        """
        Write identities into the identity hash.

        Args:
            mapping_date (datetime.date): The mapping date the identities belong to.
            identities (dict): Mapping of instrument id to its identity dict.

        Returns:
            bool: True when the write went through, False when Redis was not usable.
        """
        client = self.connection.client()
        if client is None:
            return False
        if not identities:
            return True

        fields = {}
        for instrument_identifier, identity in identities.items():
            fields[instrument_identifier] = self.encode_identity(identity)

        try:
            pipeline = client.pipeline()
            pipeline.hset(self.identity_key(mapping_date), mapping=fields)
            pipeline.expire(self.identity_key(mapping_date), self.seconds_until_midnight())
            pipeline.execute()
        except redis.RedisError:
            return False
        return True

    def read_token_identifiers(self, mapping_date, broker, broker_tokens):
        """
        Read one broker's tokens out of the token hash, as the instrument ids each carries.

        The identities themselves are not read here, because the caller already knows which of them this process holds and only the rest are worth a round trip.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            broker (str): The broker name, for example "zerodha".
            broker_tokens (list[str]): The tokens to read.

        Returns:
            dict: Mapping of broker token to a list of instrument ids, in tie-break order. Tokens Redis did not hold are absent.
        """
        client = self.connection.client()
        if client is None:
            return {}
        if not broker_tokens:
            return {}

        try:
            stored = client.hmget(self.tokens_key(mapping_date, broker), broker_tokens)
        except redis.RedisError:
            return {}

        identifiers_by_token = {}
        for position, token in enumerate(broker_tokens):
            joined = as_text(stored[position])
            if joined is None:
                continue
            identifiers_by_token[token] = joined.split(",")
        return identifiers_by_token

    def write_token_candidates(self, mapping_date, broker, candidates_by_token):
        """
        Write tokens and the identities they carry, in one pipeline.

        Both hashes are written together because the token hash holds only instrument ids and is unreadable without the identities they name.

        The candidates are stored as their instrument ids joined by commas rather than as JSON, because a UUID contains no comma, the overwhelming majority of tokens have exactly one candidate, and splitting on a comma is cheaper than parsing JSON in the path this exists to make fast.

        Args:
            mapping_date (datetime.date): The mapping date the answers belong to.
            broker (str): The broker name, for example "zerodha".
            candidates_by_token (dict): Mapping of broker token to a list of identity dicts.

        Returns:
            bool: True when the write went through, False when Redis was not usable.
        """
        client = self.connection.client()
        if client is None:
            return False

        token_fields = {}
        identity_fields = {}
        for token, candidates in candidates_by_token.items():
            identifiers = []
            for identity in candidates:
                identifiers.append(identity["instrument_id"])
                identity_fields[identity["instrument_id"]] = self.encode_identity(identity)
            token_fields[token] = ",".join(identifiers)

        if not token_fields:
            return True

        expiry_seconds = self.seconds_until_midnight()
        try:
            pipeline = client.pipeline()
            pipeline.hset(self.tokens_key(mapping_date, broker), mapping=token_fields)
            pipeline.expire(self.tokens_key(mapping_date, broker), expiry_seconds)
            if identity_fields:
                pipeline.hset(self.identity_key(mapping_date), mapping=identity_fields)
                pipeline.expire(self.identity_key(mapping_date), expiry_seconds)
            pipeline.execute()
        except redis.RedisError:
            return False
        return True

    def read_order_handles(self, mapping_date, instrument_identifiers):
        """
        Read instruments' order handles out of the order handle hash.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            instrument_identifiers (list[str]): The instrument ids to read.

        Returns:
            dict: Mapping of instrument id to a dict of broker name to that broker's handle. Instruments Redis did not hold, and instruments held in an older shape, are absent.
        """
        client = self.connection.client()
        if client is None:
            return {}
        if not instrument_identifiers:
            return {}

        try:
            stored = client.hmget(self.order_handles_key(mapping_date), instrument_identifiers)
        except redis.RedisError:
            return {}

        handles_by_instrument = {}
        for position, instrument_identifier in enumerate(instrument_identifiers):
            if stored[position] is None:
                continue
            handles_by_broker = self.decode_order_handles(stored[position])
            if handles_by_broker is not None:
                handles_by_instrument[instrument_identifier] = handles_by_broker
        return handles_by_instrument

    def write_order_handles(self, mapping_date, handles_by_instrument):
        """
        Write instruments' order handles into the order handle hash.

        This is the only writer of that hash, the daily warm included, which is what keeps the shape written and the shape read the same.

        Args:
            mapping_date (datetime.date): The mapping date the answers belong to.
            handles_by_instrument (dict): Mapping of instrument id to a dict of broker name to that broker's handle.

        Returns:
            bool: True when the write went through, False when Redis was not usable.
        """
        client = self.connection.client()
        if client is None:
            return False
        if not handles_by_instrument:
            return True

        fields = {}
        for instrument_identifier, handles_by_broker in handles_by_instrument.items():
            fields[instrument_identifier] = self.encode_order_handles(handles_by_broker)

        try:
            pipeline = client.pipeline()
            pipeline.hset(self.order_handles_key(mapping_date), mapping=fields)
            pipeline.expire(self.order_handles_key(mapping_date), self.seconds_until_midnight())
            pipeline.execute()
        except redis.RedisError:
            return False
        return True

    def write_fields(self, key, fields, expiry_seconds):
        """
        Write one batch of hash fields and set the hash to expire.

        This is the batched write a warm streams into, where the expiry is computed once for the whole command rather than per batch.

        Args:
            key (str): The hash to write into.
            fields (dict): The fields to write, as field name to value.
            expiry_seconds (int): How long the hash may live.

        Returns:
            int: The number of fields written, which is zero when there were none or when Redis was not usable.
        """
        client = self.connection.client()
        if client is None:
            return 0
        if not fields:
            return 0

        try:
            pipeline = client.pipeline()
            pipeline.hset(key, mapping=fields)
            pipeline.expire(key, expiry_seconds)
            pipeline.execute()
        except redis.RedisError:
            return 0
        return len(fields)

    def clear_other_dates(self, mapping_date):
        """
        Delete every cached mapping date except the one given.

        The dated keys expire on their own at the end of the day, so this exists for the case where a warm is re-run for a corrected date and the superseded date's keys would otherwise still be answerable.

        Args:
            mapping_date (datetime.date): The date to keep.

        Returns:
            int: The number of keys deleted.
        """
        client = self.connection.client()
        if client is None:
            return 0

        keep = f"{self.KEY_PREFIX}{mapping_date.isoformat()}:"
        deleted = 0
        try:
            for key in client.scan_iter(match=f"{self.KEY_PREFIX}*"):
                name = as_text(key)
                if name == self.current_date_key():
                    continue
                if name == self.warm_identifier_key():
                    continue
                if name.startswith(keep):
                    continue
                client.delete(name)
                deleted += 1
        except redis.RedisError:
            return deleted
        return deleted


class MappingPostgresTier:
    """
    Every statement the cache and the warm run against the mapped instrument tables.

    The tie-break ordering appears in one place here rather than in three files, because the cached answer and the database answer have to agree field for field and the verification compares them. ``ORDER BY broker_token, symbol ASC, instrument_id ASC`` is total only because an instrument id is unique; ``unified.instruments.symbol`` is null on every option row, so without the final term Postgres has no defined order among equal keys and one token carrying several options resolves differently from call to call.

    Attributes:
        STREAM_ROW_BUFFER (int): How many rows a streaming read buffers, so a whole-table pass does not hold the table.
        engine (sqlalchemy.engine.Engine): The SQLAlchemy engine over TimescaleDB.
    """

    STREAM_ROW_BUFFER = 20000

    def __init__(self, engine=None):
        """
        Build the tier around a database engine.

        Args:
            engine (sqlalchemy.engine.Engine): A SQLAlchemy engine over TimescaleDB. None builds one from the environment.

        Returns:
            None: This function returns nothing.
        """
        self.engine = engine or get_postgres_engine()

    def latest_mapping_date(self):
        """
        Read the latest mapping date straight from Postgres.

        This costs about 1.2 seconds, because a max over the whole hypertable has no selective filter of its own and scans every chunk. It is the fallback for a Redis that has never been warmed, never the read path.

        Returns:
            datetime.date | None: The latest mapping date, or None when nothing has been mapped.
        """
        with self.engine.connect() as connection:
            return connection.execute(
                text(f"SELECT max(mapping_date) FROM {tables.BROKER_MAPPINGS}")
            ).scalar()

    def read_token_candidates(self, mapping_date, broker, broker_tokens):
        """
        Read one broker's tokens, with every candidate identity each token carries.

        The mapping date is bound rather than derived, because a max over the hypertable is a hundred times more expensive than the look-up it would serve.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            broker (str): The broker name, for example "zerodha".
            broker_tokens (list[str]): The tokens to read.

        Returns:
            dict: Mapping of broker token to a list of identity dicts, in tie-break order. Tokens with no mapping on the date are absent.
        """
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT b.broker_token, b.mapping_date, m.instrument_id, m.exchange, m.segment, m.shape, "
                    "  m.symbol, m.underlying_symbol, m.expiry_date, m.strike_price, m.option_type "
                    f"FROM {tables.BROKER_MAPPINGS} b "
                    f"JOIN {tables.MASTER} m ON m.instrument_id = b.instrument_id "
                    "WHERE b.broker = :broker AND b.mapping_date = :mapping_date "
                    "  AND b.broker_token = ANY(:tokens) "
                    "ORDER BY b.broker_token, m.symbol ASC, m.instrument_id ASC"
                ),
                {
                    "broker": broker,
                    "mapping_date": mapping_date,
                    "tokens": broker_tokens,
                },
            ).all()

        candidates_by_token = {}
        for row in rows:
            candidates_by_token.setdefault(row.broker_token, []).append(self.identity_from_row(row, row.mapping_date))
        return candidates_by_token

    def read_identities(self, mapping_date, instrument_identifiers):
        """
        Read instruments' identities straight out of unified.instruments.

        The mapping date is taken rather than derived, and is used only to stamp the identity, because unified.instruments is not a hypertable and carries one row per instrument for all time.

        Args:
            mapping_date (datetime.date): The mapping date to stamp on each identity.
            instrument_identifiers (list[str]): The instrument ids to read.

        Returns:
            dict: Mapping of instrument id to its identity dict. Instruments the master does not hold are absent.
        """
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT instrument_id, exchange, segment, shape, symbol, underlying_symbol, "
                    "  expiry_date, strike_price, option_type "
                    f"FROM {tables.MASTER} "
                    "WHERE instrument_id = ANY(CAST(:instrument_identifiers AS uuid[]))"
                ),
                {
                    "instrument_identifiers": instrument_identifiers,
                },
            ).all()

        identities = {}
        for row in rows:
            identities[str(row.instrument_id)] = self.identity_from_row(row, mapping_date)
        return identities

    def read_order_handles(self, mapping_date, instrument_identifiers):
        """
        Read instruments' order handles for one mapping date.

        Four columns are read rather than one because everything an order needs about an instrument at a broker is here, and reading the token now and the symbol, lot size and tick size later would be two queries for one answer on a path that must not make even one.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            instrument_identifiers (list[str]): The instrument ids to read.

        Returns:
            dict: Mapping of instrument id to a dict of broker name to that broker's handle. Instruments with no mapping on the date are absent.
        """
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT instrument_id, broker, broker_token, order_symbol, lot_size, tick_size "
                    f"FROM {tables.BROKER_MAPPINGS} "
                    "WHERE instrument_id = ANY(CAST(:instrument_identifiers AS uuid[])) "
                    "  AND mapping_date = :mapping_date "
                    "ORDER BY instrument_id, broker"
                ),
                {
                    "instrument_identifiers": instrument_identifiers,
                    "mapping_date": mapping_date,
                },
            ).all()

        handles_by_instrument = {}
        for row in rows:
            handles_by_instrument.setdefault(str(row.instrument_id), {})[row.broker] = self.handle_from_row(row)
        return handles_by_instrument

    def broker_tokens_on_date(self, mapping_date, broker):
        """
        Every token one broker maps on one date, which is what a whole-broker warm has to resolve.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            broker (str): The broker name, for example "zerodha".

        Returns:
            list[str]: The broker's tokens on that date.
        """
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT DISTINCT broker_token FROM {tables.BROKER_MAPPINGS} "
                    "WHERE broker = :broker AND mapping_date = :mapping_date"
                ),
                {
                    "broker": broker,
                    "mapping_date": mapping_date,
                },
            ).all()

        tokens = []
        for row in rows:
            tokens.append(row.broker_token)
        return tokens

    def stream_identities(self, mapping_date):
        """
        Yield the identity of every instrument mapped on the date, one at a time.

        The identity is produced once per instrument rather than once per token, because several brokers' tokens point at one instrument and repeating it per token would about double the work.

        Args:
            mapping_date (datetime.date): The mapping date to read.

        Yields:
            dict: One identity dict.
        """
        statement = text(
            "SELECT DISTINCT ON (m.instrument_id) "
            "  m.instrument_id, m.exchange, m.segment, m.shape, m.symbol, m.underlying_symbol, "
            "  m.expiry_date, m.strike_price, m.option_type "
            f"FROM {tables.BROKER_MAPPINGS} b "
            f"JOIN {tables.MASTER} m ON m.instrument_id = b.instrument_id "
            "WHERE b.mapping_date = :mapping_date "
            "ORDER BY m.instrument_id"
        )
        with self.streaming_connection() as connection:
            for row in connection.execute(statement, {"mapping_date": mapping_date}):
                yield self.identity_from_row(row, mapping_date)

    def stream_broker_tokens(self, mapping_date, broker):
        """
        Yield one broker's token and instrument id pairs for the date, ordered so one token's rows arrive together.

        The rows arrive in the same tie-break order the point look-up uses, so the first identity stored under a token is the answer an unfiltered look-up gets.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            broker (str): The broker name, for example "zerodha".

        Yields:
            tuple: The broker token as text and the instrument id as text.
        """
        statement = text(
            "SELECT b.broker_token, m.instrument_id "
            f"FROM {tables.BROKER_MAPPINGS} b "
            f"JOIN {tables.MASTER} m ON m.instrument_id = b.instrument_id "
            "WHERE b.mapping_date = :mapping_date AND b.broker = :broker "
            "ORDER BY b.broker_token ASC, m.symbol ASC, m.instrument_id ASC"
        )
        with self.streaming_connection() as connection:
            rows = connection.execute(
                statement,
                {
                    "mapping_date": mapping_date,
                    "broker": broker,
                },
            )
            for row in rows:
                yield row.broker_token, str(row.instrument_id)

    def stream_order_handles(self, mapping_date):
        """
        Yield every instrument's order handles for the date, ordered so one instrument's rows arrive together.

        The same four columns the point look-up reads, so a warmed hash and a lazily filled one hold the same shape.

        Args:
            mapping_date (datetime.date): The mapping date to read.

        Yields:
            tuple: The instrument id as text, the broker name, and that broker's handle dict.
        """
        statement = text(
            "SELECT instrument_id, broker, broker_token, order_symbol, lot_size, tick_size "
            f"FROM {tables.BROKER_MAPPINGS} "
            "WHERE mapping_date = :mapping_date "
            "ORDER BY instrument_id ASC, broker ASC"
        )
        with self.streaming_connection() as connection:
            for row in connection.execute(statement, {"mapping_date": mapping_date}):
                yield str(row.instrument_id), row.broker, self.handle_from_row(row)

    def stream_catalogue(self, mapping_date):
        """
        Yield the identity and seen dates of every instrument mapped on the date, one at a time.

        The same instruments as stream_identities, with the two columns a catalogue needs beyond the identity.

        Args:
            mapping_date (datetime.date): The mapping date to read.

        Yields:
            tuple: The identity dict, its first seen date and its last seen date.
        """
        statement = text(
            "SELECT DISTINCT ON (m.instrument_id) "
            "  m.instrument_id, m.exchange, m.segment, m.shape, m.symbol, m.underlying_symbol, "
            "  m.expiry_date, m.strike_price, m.option_type, m.first_seen_date, m.last_seen_date "
            f"FROM {tables.BROKER_MAPPINGS} b "
            f"JOIN {tables.MASTER} m ON m.instrument_id = b.instrument_id "
            "WHERE b.mapping_date = :mapping_date "
            "ORDER BY m.instrument_id"
        )
        with self.streaming_connection() as connection:
            for row in connection.execute(statement, {"mapping_date": mapping_date}):
                yield self.identity_from_row(row, mapping_date), row.first_seen_date, row.last_seen_date

    def streaming_connection(self):
        """
        A connection that streams its results rather than buffering the whole answer.

        A warm reads the entire mapping, which costs 829 megabytes to hold in one process. Streaming is what keeps the command that exists to spare everyone that cost from paying it itself.

        Returns:
            sqlalchemy.engine.Connection: A connection with streaming execution options set.
        """
        return self.engine.connect().execution_options(
            stream_results=True,
            max_row_buffer=self.STREAM_ROW_BUFFER,
        )

    def identity_from_row(self, row, mapping_date):
        """
        Build one identity dictionary from a database row.

        Args:
            row (sqlalchemy.engine.Row): A row carrying the nine identity columns of unified.instruments.
            mapping_date (datetime.date): The mapping date to stamp on the identity.

        Returns:
            dict: The identity, with its instrument id as text.
        """
        return {
            "instrument_id": str(row.instrument_id),
            "exchange": row.exchange,
            "segment": row.segment,
            "shape": row.shape,
            "symbol": row.symbol,
            "underlying_symbol": row.underlying_symbol,
            "expiry_date": row.expiry_date,
            "strike_price": row.strike_price,
            "option_type": row.option_type,
            "mapping_date": mapping_date,
        }

    def handle_from_row(self, row):
        """
        Build one broker's order handle from a database row.

        The lot and tick sizes are kept as text rather than as decimals, because the handle is stored in Redis as JSON and a decimal that survives the round trip as a float would be a price-sized rounding error in a quantity.

        Args:
            row (sqlalchemy.engine.Row): A row carrying broker_token, order_symbol, lot_size and tick_size.

        Returns:
            dict: The handle, with keys "broker_token", "order_symbol", "lot_size" and "tick_size".
        """
        return {
            "broker_token": row.broker_token,
            "order_symbol": row.order_symbol,
            "lot_size": None if row.lot_size is None else str(row.lot_size),
            "tick_size": None if row.tick_size is None else str(row.tick_size),
        }


class ThreeTierLookup:
    """
    The walk from this process's memory to Redis to Postgres, shared by the three questions the cache answers.

    Each tier fills in the ones above it, so the first look-up of a key costs a Redis round trip or a Postgres query and every look-up after it costs a dictionary read. Subclasses supply the two reads and the one write; everything else about the walk, including the counting, is here.

    Attributes:
        redis_tier (MappingRedisTier): The Redis hashes this lookup reads and writes.
        postgres_tier (MappingPostgresTier): The statements this lookup falls through to.
        statistics (dict): The counters shared with every other lookup on the same cache, so the tally is per process rather than per question.
    """

    def __init__(self, redis_tier, postgres_tier, statistics):
        """
        Build the lookup around the two lower tiers and the shared counters.

        Args:
            redis_tier (MappingRedisTier): The Redis hashes to read and write.
            postgres_tier (MappingPostgresTier): The statements to fall through to.
            statistics (dict): The counters to count into.

        Returns:
            None: This function returns nothing.
        """
        self.redis_tier = redis_tier
        self.postgres_tier = postgres_tier
        self.statistics = statistics

        self._entries = {}

    def resolve(self, mapping_date, keys):
        """
        Answer for a batch of keys, trying each tier in turn and filling in the ones above.

        A key that nothing maps is remembered as an empty entry when the subclass says so, which stops a token nothing carries being asked about on every call. A subclass whose empty_entry is None does not remember misses at all.

        Args:
            mapping_date (datetime.date): The mapping date being answered for.
            keys (list[str]): The keys to answer for.

        Returns:
            dict: Mapping of key to its entry, for every key that had one. Keys nothing maps are absent, unless the subclass remembers empty entries, in which case they carry one.
        """
        if not keys:
            return {}

        resolved = {}
        outstanding = []
        for key in keys:
            entry = self._entries.get(key)
            if entry is None:
                outstanding.append(key)
                continue
            self.statistics["process_hits"] += 1
            resolved[key] = entry

        if outstanding:
            from_redis = self.read_from_redis(mapping_date, outstanding)
            still_outstanding = []
            for key in outstanding:
                if key not in from_redis:
                    still_outstanding.append(key)
                    continue
                self.statistics["redis_hits"] += 1
                self._entries[key] = from_redis[key]
                resolved[key] = from_redis[key]
            outstanding = still_outstanding

        if outstanding:
            from_postgres = self.read_from_postgres(mapping_date, outstanding)
            for key in outstanding:
                entry = from_postgres.get(key)
                if entry is None:
                    self.statistics["misses"] += 1
                    empty = self.empty_entry()
                    if empty is not None:
                        self._entries[key] = empty
                        resolved[key] = empty
                    continue
                self.statistics["postgres_hits"] += 1
                self._entries[key] = entry
                resolved[key] = entry
            self.write_to_redis(mapping_date, from_postgres)

        return resolved

    def remember(self, key, entry):
        """
        Put one entry into this process's memory without going to any other tier.

        This exists so that a lookup filling itself can also fill a sibling, which is how a token's candidate identities land in the identity lookup rather than being read again from Redis.

        Args:
            key (str): The key to remember the entry under.
            entry (dict): The entry to remember.

        Returns:
            None: This function returns nothing.
        """
        self._entries[key] = entry

    def known(self, key):
        """
        Whether this process already holds an entry for one key.

        Args:
            key (str): The key to test.

        Returns:
            bool: True when the entry is in this process's memory.
        """
        return key in self._entries

    def entry(self, key):
        """
        The entry this process holds for one key, without reaching any other tier.

        The counterpart of remember, for a sibling lookup assembling an answer out of entries this one already has.

        Args:
            key (str): The key to read.

        Returns:
            dict | None: The entry, or None when this process does not hold one.
        """
        return self._entries.get(key)

    def reset(self):
        """
        Drop everything this lookup holds in process memory.

        Returns:
            None: This function returns nothing.
        """
        self._entries.clear()

    def empty_entry(self):
        """
        What to remember for a key nothing maps, or None to remember nothing.

        A fresh object is returned on every call rather than a shared one, so that an entry a caller narrows in place cannot reach the next key that also missed.

        Returns:
            None: The base class does not remember misses.
        """
        return None

    def read_from_redis(self, mapping_date, keys):
        """
        Read a batch of keys out of Redis.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            keys (list[str]): The keys to read.

        Returns:
            dict: Mapping of key to entry, for the keys Redis held.

        Raises:
            NotImplementedError: Always, unless the subclass overrides this method.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement read_from_redis()")

    def read_from_postgres(self, mapping_date, keys):
        """
        Read a batch of keys out of Postgres.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            keys (list[str]): The keys to read.

        Returns:
            dict: Mapping of key to entry, for the keys Postgres held.

        Raises:
            NotImplementedError: Always, unless the subclass overrides this method.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement read_from_postgres()")

    def write_to_redis(self, mapping_date, entries):
        """
        Write entries resolved from Postgres back into Redis, so the next process does not repeat the query.

        Args:
            mapping_date (datetime.date): The mapping date the entries belong to.
            entries (dict): Mapping of key to entry.

        Returns:
            bool: True when the write went through, False when Redis was not usable.

        Raises:
            NotImplementedError: Always, unless the subclass overrides this method.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement write_to_redis()")


class InstrumentIdentityLookup(ThreeTierLookup):
    """
    Instrument id to that instrument's identity.

    This is the direction a caller holding an instrument id and about to place an order on it needs: the exchange, the segment and the shape decide every broker-native code the order is sent with. It is also the store the token lookup fills, since a token's candidates are identities and the two must not hold separate copies.

    A miss is not remembered, because an instrument id the master does not carry is a caller's mistake rather than a fact about the mapping, and remembering it would keep answering a question whose answer may arrive with the next day's master.
    """

    def read_from_redis(self, mapping_date, keys):
        """
        Read identities out of the identity hash.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            keys (list[str]): The instrument ids to read.

        Returns:
            dict: Mapping of instrument id to its identity dict.
        """
        return self.redis_tier.read_identities(mapping_date, keys)

    def read_from_postgres(self, mapping_date, keys):
        """
        Read identities out of unified.instruments.

        Args:
            mapping_date (datetime.date): The mapping date to stamp on each identity.
            keys (list[str]): The instrument ids to read.

        Returns:
            dict: Mapping of instrument id to its identity dict.
        """
        return self.postgres_tier.read_identities(mapping_date, keys)

    def write_to_redis(self, mapping_date, entries):
        """
        Write identities back into the identity hash.

        Args:
            mapping_date (datetime.date): The mapping date the identities belong to.
            entries (dict): Mapping of instrument id to its identity dict.

        Returns:
            bool: True when the write went through, False when Redis was not usable.
        """
        return self.redis_tier.write_identities(mapping_date, entries)


class TokenCandidateLookup(ThreeTierLookup):
    """
    One broker's token to every identity that token carries, for one broker.

    A lookup is built per broker rather than one for all ten, so its memory is keyed by the token alone and the shared walk needs no notion of a compound key.

    A broker token can carry more than one instrument on the same date, which is why the candidates are stored in full rather than resolved once and stored as a winner. Once an optional segment filter exists the same token has two right answers depending on the filter, and caching the resolved winner would let a filtered and an unfiltered look-up contaminate each other. Storing them all is what lets both share one entry, and the filter is applied on the way out.

    Attributes:
        broker (str): The broker whose tokens this lookup answers for.
        identity_lookup (InstrumentIdentityLookup): The identity store this lookup shares, so an instrument seen from either direction costs one read.
    """

    def __init__(self, redis_tier, postgres_tier, statistics, broker, identity_lookup):
        """
        Build the lookup for one broker.

        Args:
            redis_tier (MappingRedisTier): The Redis hashes to read and write.
            postgres_tier (MappingPostgresTier): The statements to fall through to.
            statistics (dict): The counters to count into.
            broker (str): The broker whose tokens this lookup answers for.
            identity_lookup (InstrumentIdentityLookup): The identity store to share.

        Returns:
            None: This function returns nothing.
        """
        super().__init__(redis_tier, postgres_tier, statistics)
        self.broker = broker
        self.identity_lookup = identity_lookup

    def empty_entry(self):
        """
        What to remember for a token nothing maps.

        An empty candidate list is remembered, because a token a broker does not carry is a stable fact for the day and asking Postgres about it on every call would be the cost this cache exists to remove.

        Returns:
            list: A new empty list.
        """
        return []

    def read_from_redis(self, mapping_date, keys):
        """
        Read tokens out of the token hash, resolving each to its full list of candidate identities.

        The identities this process already holds are not read again, and only a token whose every candidate resolved is returned, because a partly resolved token would silently lose a candidate the segment filter might have wanted.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            keys (list[str]): The broker tokens to read.

        Returns:
            dict: Mapping of broker token to a list of identity dicts.
        """
        identifiers_by_token = self.redis_tier.read_token_identifiers(mapping_date, self.broker, keys)
        if not identifiers_by_token:
            return {}

        wanted_identifiers = []
        already_wanted = set()
        for identifiers in identifiers_by_token.values():
            for instrument_identifier in identifiers:
                if self.identity_lookup.known(instrument_identifier):
                    continue
                if instrument_identifier in already_wanted:
                    continue
                already_wanted.add(instrument_identifier)
                wanted_identifiers.append(instrument_identifier)

        if wanted_identifiers:
            from_redis = self.redis_tier.read_identities(mapping_date, wanted_identifiers)
            for instrument_identifier, identity in from_redis.items():
                self.identity_lookup.remember(instrument_identifier, identity)

        candidates_by_token = {}
        for token, identifiers in identifiers_by_token.items():
            candidates = []
            for instrument_identifier in identifiers:
                identity = self.identity_lookup.entry(instrument_identifier)
                if identity is not None:
                    candidates.append(identity)
            if len(candidates) == len(identifiers):
                candidates_by_token[token] = candidates
        return candidates_by_token

    def read_from_postgres(self, mapping_date, keys):
        """
        Read tokens out of Postgres, with every candidate identity each token carries.

        The identities are remembered in the shared identity store on the way past, so an instrument reached first through a token costs nothing when it is later asked about by id.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            keys (list[str]): The broker tokens to read.

        Returns:
            dict: Mapping of broker token to a list of identity dicts, in tie-break order.
        """
        candidates_by_token = self.postgres_tier.read_token_candidates(mapping_date, self.broker, keys)
        for candidates in candidates_by_token.values():
            for identity in candidates:
                self.identity_lookup.remember(identity["instrument_id"], identity)
        return candidates_by_token

    def write_to_redis(self, mapping_date, entries):
        """
        Write tokens and the identities they carry back into Redis.

        Args:
            mapping_date (datetime.date): The mapping date the answers belong to.
            entries (dict): Mapping of broker token to a list of identity dicts.

        Returns:
            bool: True when the write went through, False when Redis was not usable.
        """
        return self.redis_tier.write_token_candidates(mapping_date, self.broker, entries)


class OrderHandleLookup(ThreeTierLookup):
    """
    Instrument id to every broker's order handle for that instrument.

    A handle is everything an order needs to name an instrument at one broker: the broker's own token, the tradeable symbol where that broker orders by symbol rather than by token, and the lot and tick sizes an order has to be a multiple of. All four come out of one row, so an order placement costs one dictionary look-up once this process has seen the instrument, and one query the first time it has not.
    """

    def empty_entry(self):
        """
        What to remember for an instrument no broker maps on the date.

        Returns:
            dict: A new empty dictionary.
        """
        return {}

    def read_from_redis(self, mapping_date, keys):
        """
        Read order handles out of the order handle hash.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            keys (list[str]): The instrument ids to read.

        Returns:
            dict: Mapping of instrument id to a dict of broker name to handle.
        """
        return self.redis_tier.read_order_handles(mapping_date, keys)

    def read_from_postgres(self, mapping_date, keys):
        """
        Read order handles out of unified.broker_mappings.

        Args:
            mapping_date (datetime.date): The mapping date to read.
            keys (list[str]): The instrument ids to read.

        Returns:
            dict: Mapping of instrument id to a dict of broker name to handle.
        """
        return self.postgres_tier.read_order_handles(mapping_date, keys)

    def write_to_redis(self, mapping_date, entries):
        """
        Write order handles back into the order handle hash.

        Args:
            mapping_date (datetime.date): The mapping date the answers belong to.
            entries (dict): Mapping of instrument id to a dict of broker name to handle.

        Returns:
            bool: True when the write went through, False when Redis was not usable.
        """
        return self.redis_tier.write_order_handles(mapping_date, entries)


class MappingCache:
    """
    A three tier cache in front of the mapped instrument tables, holding its own engine.

    One of these belongs to a process, not to a call. The memory tier is the whole point of it, and two of them in one process would hold two copies of everything and halve the hit rate, so a caller builds one and passes it down. The engine is available as an attribute for the callers that need one of their own.

    Attributes:
        engine (sqlalchemy.engine.Engine): The SQLAlchemy engine over TimescaleDB.
        redis_tier (MappingRedisTier): The Redis hashes, read and written through one class.
        postgres_tier (MappingPostgresTier): Every statement, in one class.
        statistics (dict): Counts with keys "process_hits", "redis_hits", "postgres_hits" and "misses", shared by every lookup.
    """

    def __init__(self, engine=None, redis_connection=None):
        """
        Build the cache and its tiers.

        Args:
            engine (sqlalchemy.engine.Engine): A SQLAlchemy engine over TimescaleDB. None builds one from the environment.
            redis_connection (MappingRedisConnection | None): The Redis connection to use. None builds one.

        Returns:
            None: This function returns nothing.
        """
        self.postgres_tier = MappingPostgresTier(engine)
        self.engine = self.postgres_tier.engine
        self.redis_tier = MappingRedisTier(redis_connection)
        self.statistics = {
            "process_hits": 0,
            "redis_hits": 0,
            "postgres_hits": 0,
            "misses": 0,
        }

        self._identity_lookup = InstrumentIdentityLookup(self.redis_tier, self.postgres_tier, self.statistics)
        self._order_handle_lookup = OrderHandleLookup(self.redis_tier, self.postgres_tier, self.statistics)
        self._token_lookups = {}
        self._mapping_date = None
        self._mapping_date_read_at = 0.0

    def current_mapping_date(self):
        """
        The mapping date the cache covers, read from Redis and remembered in this process.

        The date is re-read every five minutes rather than once, because a process that streams ticks all day would otherwise serve yesterday's mappings after the morning's download. When the date has moved, this process's own dictionaries are dropped, since every entry in them belongs to the date that has just been superseded.

        Returns:
            datetime.date | None: The mapping date the cache covers, or None when nothing has been mapped at all.
        """
        if self._mapping_date is not None and time.monotonic() - self._mapping_date_read_at < CURRENT_DATE_REFRESH_SECONDS:
            return self._mapping_date

        mapping_date = self.redis_tier.read_current_date()
        if mapping_date is None:
            mapping_date = self.postgres_tier.latest_mapping_date()
        if mapping_date is None:
            return None

        if self._mapping_date is not None and mapping_date != self._mapping_date:
            self.reset()
        self._mapping_date = mapping_date
        self._mapping_date_read_at = time.monotonic()
        return self._mapping_date

    def resolves_to_current_date(self, as_of_date):
        """
        Decide whether a request for one as-of date can be answered from the cache.

        Args:
            as_of_date (datetime.date): The date the caller asked about.

        Returns:
            datetime.date | None: The current mapping date when the request lands on it, or None when the request is for an earlier date and must go to Postgres.
        """
        mapping_date = self.current_mapping_date()
        if mapping_date is None:
            return None
        if as_of_date < mapping_date:
            return None
        return mapping_date

    def identities_for_tokens(self, broker, broker_tokens, as_of_date, segments=None):
        """
        Resolve one broker's tokens to unified identities, through the cache.

        A request for a date earlier than the cached mapping date is refused here and belongs in resolution.py, which goes straight to Postgres for it.

        Args:
            broker (str): The broker name, for example "zerodha".
            broker_tokens (list[str]): The broker's own tokens to resolve.
            as_of_date (datetime.date): The date the caller asked about, which must land on the current mapping date.
            segments (list[str] | None): Canonical segment names to restrict the answer to, or None to accept any segment.

        Returns:
            dict: Mapping of broker token to an identity dict. Tokens with no mapping, and tokens whose only mappings fall outside the requested segments, are absent.

        Raises:
            ValueError: If the request is for a date the cache does not cover, which the caller should have tested with resolves_to_current_date.
        """
        mapping_date = self._mapping_date_for(as_of_date)
        if not broker_tokens:
            return {}

        tokens = []
        for token in broker_tokens:
            tokens.append(str(token))

        candidates_by_token = self._token_lookup(broker).resolve(mapping_date, tokens)

        resolved = {}
        for token, candidates in candidates_by_token.items():
            chosen = self._choose_candidate(candidates, segments)
            if chosen is not None:
                resolved[token] = chosen
        return resolved

    def candidates_for_tokens(self, broker, broker_tokens, as_of_date, segments=None):
        """
        Every identity one broker's tokens map to, through the cache, rather than one chosen identity.

        identities_for_tokens answers with the first candidate inside the segment filter, which is right for a caller that has to act on some answer. A caller that must not guess - the unified tick service, which would otherwise write one instrument's prices under another's id - needs to see that a token is ambiguous, and this gives it every candidate so it can decide.

        Args:
            broker (str): The broker name, for example "zerodha".
            broker_tokens (list[str]): The broker's own tokens to resolve.
            as_of_date (datetime.date): The date the caller asked about, which must land on the current mapping date.
            segments (list[str] | None): Canonical segment names to restrict the answer to, or None to accept any segment.

        Returns:
            dict: Mapping of broker token to a list of identity dicts in tie-break order. Tokens with no candidate inside the requested segments are absent.

        Raises:
            ValueError: If the request is for a date the cache does not cover, which the caller should have tested with resolves_to_current_date.
        """
        mapping_date = self._mapping_date_for(as_of_date)
        if not broker_tokens:
            return {}

        tokens = []
        for token in broker_tokens:
            tokens.append(str(token))

        candidates_by_token = self._token_lookup(broker).resolve(mapping_date, tokens)

        resolved = {}
        for token, candidates in candidates_by_token.items():
            kept = []
            for candidate in candidates:
                if segments is None or candidate["segment"] in segments:
                    kept.append(candidate)
            if kept:
                resolved[token] = kept
        return resolved

    def identities_for_instruments(self, instrument_identifiers, as_of_date):
        """
        Resolve unified instrument ids to their identities, through the cache.

        The reverse direction of identities_for_tokens. It shares the identity store the token path already fills rather than keeping one of its own, so an instrument this process has already seen from either direction costs a dictionary look-up.

        Args:
            instrument_identifiers (list[str]): The instrument ids to resolve.
            as_of_date (datetime.date): The date the caller asked about, which must land on the current mapping date.

        Returns:
            dict: Mapping of instrument id to its identity dict. Instruments the master does not hold are absent.

        Raises:
            ValueError: If the request is for a date the cache does not cover, which the caller should have tested with resolves_to_current_date.
        """
        mapping_date = self._mapping_date_for(as_of_date)
        if not instrument_identifiers:
            return {}

        identifiers = []
        for instrument_identifier in instrument_identifiers:
            identifiers.append(str(instrument_identifier))

        return self._identity_lookup.resolve(mapping_date, identifiers)

    def order_handles_for_instruments(self, instrument_identifiers, as_of_date, brokers=None):
        """
        Resolve unified identities to every broker's order handle for them, through the cache.

        Args:
            instrument_identifiers (list[str]): The instrument ids to resolve.
            as_of_date (datetime.date): The date the caller asked about, which must land on the current mapping date.
            brokers (list[str] | None): Broker names to restrict the answer to, or None for every broker that maps the instrument.

        Returns:
            dict: Mapping of instrument id to a dict of broker name to that broker's handle, itself a dict with keys "broker_token", "order_symbol", "lot_size" and "tick_size", where the last three are strings or None. Instruments with no mapping, and instruments no requested broker maps, are absent.

        Raises:
            ValueError: If the request is for a date the cache does not cover, which the caller should have tested with resolves_to_current_date.
        """
        mapping_date = self._mapping_date_for(as_of_date)
        if not instrument_identifiers:
            return {}

        identifiers = []
        for instrument_identifier in instrument_identifiers:
            identifiers.append(str(instrument_identifier))

        handles_by_instrument = self._order_handle_lookup.resolve(mapping_date, identifiers)

        resolved = {}
        for instrument_identifier, handles_by_broker in handles_by_instrument.items():
            narrowed = self._restrict_to_brokers(handles_by_broker, brokers)
            if narrowed:
                resolved[instrument_identifier] = narrowed
        return resolved

    def tokens_for_instruments(self, instrument_identifiers, as_of_date, brokers=None):
        """
        Resolve unified identities to every broker's token for them, through the cache.

        A projection of order_handles_for_instruments, for a caller that wants only the token. It shares that method's entries rather than keeping its own, so a market feed subscribing to an instrument and an order placed on the same instrument cost one query between them rather than two.

        Args:
            instrument_identifiers (list[str]): The instrument ids to resolve.
            as_of_date (datetime.date): The date the caller asked about, which must land on the current mapping date.
            brokers (list[str] | None): Broker names to restrict the answer to, or None for every broker that maps the instrument.

        Returns:
            dict: Mapping of instrument id to a dict of broker name to broker token. Instruments with no mapping, and instruments no requested broker maps, are absent.

        Raises:
            ValueError: If the request is for a date the cache does not cover, which the caller should have tested with resolves_to_current_date.
        """
        handles = self.order_handles_for_instruments(instrument_identifiers, as_of_date, brokers)
        tokens = {}
        for instrument_identifier, handles_by_broker in handles.items():
            for broker, handle in handles_by_broker.items():
                tokens.setdefault(instrument_identifier, {})[broker] = handle["broker_token"]
        return tokens

    def warm(self, as_of_date, instrument_identifiers=None, brokers=None):
        """
        Fill this process's memory up front, for a process that knows its universe before it starts.

        This is deliberately optional and never happens by itself. Loading every broker's mappings into one process costs 4.06 seconds and 829 megabytes, which is why the default is to cache only what the process actually looks up. One broker alone costs about 0.21 seconds and 51 megabytes, which a strategy that knows its universe can reasonably pay at startup.

        Args:
            as_of_date (datetime.date): The date to warm for, which must land on the current mapping date.
            instrument_identifiers (list[str] | None): Instruments whose broker tokens to load, or None to load none.
            brokers (list[str] | None): Brokers whose entire token map to load, or None to load none.

        Returns:
            dict: The counts loaded, with keys "instruments" and "tokens".

        Raises:
            ValueError: If the request is for a date the cache does not cover.
        """
        mapping_date = self._mapping_date_for(as_of_date)

        loaded = {
            "instruments": 0,
            "tokens": 0,
        }

        if instrument_identifiers:
            resolved = self.tokens_for_instruments(instrument_identifiers, as_of_date)
            loaded["instruments"] = len(resolved)

        if brokers:
            for broker in brokers:
                tokens = self.postgres_tier.broker_tokens_on_date(mapping_date, broker)
                for start in range(0, len(tokens), READ_BATCH_TOKENS):
                    self.identities_for_tokens(broker, tokens[start:start + READ_BATCH_TOKENS], as_of_date)
                loaded["tokens"] += len(tokens)

        return loaded

    def cache_statistics(self):
        """
        How many look-ups each tier has answered in this process.

        A cache that silently never hits looks exactly like one that works, so the counts are part of the interface rather than decoration. They count items looked up, not calls made, since one call resolves many tokens at once.

        Returns:
            dict: Counts with keys "process_hits", "redis_hits", "postgres_hits" and "misses", where a miss is an item nothing maps at all.
        """
        return dict(self.statistics)

    def reset(self):
        """
        Drop everything this process has cached, including the counts and the remembered mapping date.

        This exists for the verification report, which has to resolve a sample cold and then again warm, and for the day boundary, where every cached entry belongs to a mapping date that has just been superseded.

        Returns:
            None: This function returns nothing.
        """
        self._identity_lookup.reset()
        self._order_handle_lookup.reset()
        for lookup in self._token_lookups.values():
            lookup.reset()
        for counter in self.statistics:
            self.statistics[counter] = 0
        self._mapping_date = None
        self._mapping_date_read_at = 0.0

    def _mapping_date_for(self, as_of_date):
        """
        The mapping date a request may be answered on, or a refusal.

        Args:
            as_of_date (datetime.date): The date the caller asked about.

        Returns:
            datetime.date: The current mapping date.

        Raises:
            ValueError: If the request is for a date the cache does not cover.
        """
        mapping_date = self.resolves_to_current_date(as_of_date)
        if mapping_date is None:
            raise ValueError(f"the cache covers only the current mapping date, not {as_of_date}")
        return mapping_date

    def _token_lookup(self, broker):
        """
        The token lookup for one broker, built on first use.

        Args:
            broker (str): The broker name, for example "zerodha".

        Returns:
            TokenCandidateLookup: That broker's lookup.
        """
        lookup = self._token_lookups.get(broker)
        if lookup is None:
            lookup = TokenCandidateLookup(
                self.redis_tier,
                self.postgres_tier,
                self.statistics,
                broker,
                self._identity_lookup,
            )
            self._token_lookups[broker] = lookup
        return lookup

    def _choose_candidate(self, candidates, segments):
        """
        Pick one identity out of a token's candidates, honouring an optional segment filter.

        Args:
            candidates (list[dict]): The token's identities, in tie-break order so the choice is stable between calls.
            segments (list[str] | None): Canonical segment names to restrict the answer to, or None to accept any segment.

        Returns:
            dict | None: The chosen identity, or None when no candidate is in the requested segments.
        """
        for candidate in candidates:
            if segments is None or candidate["segment"] in segments:
                return candidate
        return None

    def _restrict_to_brokers(self, handles_by_broker, brokers):
        """
        Narrow one instrument's order handles to the brokers the caller asked for.

        Args:
            handles_by_broker (dict): Mapping of broker name to that broker's handle.
            brokers (list[str] | None): Broker names to keep, or None to keep every one.

        Returns:
            dict: The mapping, narrowed to the requested brokers.
        """
        if brokers is None:
            return handles_by_broker
        narrowed = {}
        for broker in brokers:
            if broker in handles_by_broker:
                narrowed[broker] = handles_by_broker[broker]
        return narrowed
