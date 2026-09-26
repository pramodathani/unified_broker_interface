"""
The instrument universe as the REST API sees it: segments, listings, search, details and resolving a
request to one instrument.

Everything is answered from the Redis tier of the instrument mapping cache, which the daily warm fills
for the current mapping date: the identity, order handle and additional attribute hashes, and the
catalogue it builds for browsing and searching - one sorted set per segment in name, expiry, strike and
option type order, a set of each segment's distinct names, each instrument's first and last seen dates,
and a count per segment. See `stock_brokers/instruments/mapping/utilities/cache.py`.

The tables are the unified ones, `unified.instruments` and `unified.broker_mappings`, which `bin/unified/instruments/map`
maps and warms the cache from; every query here names its tables through
`stock_brokers.instruments.mapping.utilities.tables`. TimescaleDB is read only when the cache cannot answer, and each time it is, it is logged:

- **a past date** - the cache holds only the current mapping date, by design, so a `date` before it
  is answered from the instrument and broker mapping tables;
- **a cold cache** - the date's catalogue has not been warmed, because Redis was flushed or the
  midnight expiry passed before the morning warm;
- **history of an instrument no longer mapped** - an expired contract or a delisted stock is absent
  from today's cache but still has prices, so `/prices` and `/ticks` look it up in the instrument table.
"""

from collections import Counter
from decimal import Decimal, InvalidOperation

from sqlalchemy import text

from stock_brokers.instruments.mapping.utilities import tables
from stock_brokers.instruments.mapping.utilities.raw_attributes import ATTRIBUTE_NAMES, RawAttributes
from stock_brokers.instruments.mapping.utilities.resolution import MappingResolver
from stock_brokers.instruments.mapping.utilities.segments import segment_rank, split_segment_value
from stock_brokers.instruments.ticks.utilities.resolution import units_per_lot
from unified_broker_interface.utilities.instrument_identity import (IDENTITY_FIELDS, UNCATEGORISED, RequestError,
                                                                    identity_to_json, shape_of)
from utilities.configurations import get_logger

logger = get_logger("rest_api.instruments")

# How many instruments a listing reads from Redis at a time.
BATCH = 5000

_IDENTITY_COLUMNS = ("m.instrument_id, m.exchange, m.segment, m.shape, m.symbol, m.underlying_symbol, "
                     "m.expiry_date, m.strike_price, m.option_type")

_NAME = "upper(coalesce(m.symbol, m.underlying_symbol))"

_LISTING_ORDER = f"m.segment, {_NAME}, m.expiry_date, m.strike_price, m.option_type"

def _mapped_on():
    """The condition that an instrument `m` was mapped on `:mapping_date`, against the broker mapping table in use."""
    return (f"EXISTS (SELECT 1 FROM {tables.BROKER_MAPPINGS} b "
            "WHERE b.instrument_id = m.instrument_id AND b.mapping_date = :mapping_date)")

def _segment_order(segment):
    """
    Sort key putting segments in the canonical vocabulary's order, with anything unrecognised last.

    - `segment` is an exchange-prefixed segment.
    """
    exchange, bare = split_segment_value(segment)
    try:
        return (0, segment_rank(exchange, bare))
    except KeyError:
        return (1, (segment,))

def _escape_like(value):
    """
    A search term with LIKE's wildcards escaped.

    - `value` is the term.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

class InstrumentCatalogue:
    """
    Answers the instrument lookup endpoints from the mapping cache.

    Attributes:
        cache (MappingCache): The worker's mapping cache.
        redis (MappingRedisTier): Its Redis tier, read directly so a miss is an answer rather than a fall-through to Postgres.
        engine (sqlalchemy.engine.Engine): For the past-date and cold-cache paths only.
    """

    def __init__(self, mapping_cache):
        """
        - `mapping_cache` is the worker's `MappingCache`.
        """
        self.cache = mapping_cache
        self.redis = mapping_cache.redis_tier
        self.engine = mapping_cache.engine
        self._resolver = MappingResolver(mapping_cache)
        self._raw_attributes = RawAttributes()

    def mapping_date(self, as_of=None):
        """
        The mapping date a request is answered on, and whether the cache holds it.

        Returns a pair `(mapping_date, counts)`, where `counts` is the per-segment instrument count from
        the cache, or None when the answer must come from Postgres.

        - `as_of` is the date the request asked about, or None for today.
        """
        current = self.cache.current_mapping_date()
        if current is None:
            raise RequestError("no instruments have been mapped yet", 503)
        if as_of is None or as_of >= current:
            counts = self.redis.read_segment_counts(current)
            if counts is None:
                logger.warning(f"the instrument catalogue for {current} is not in Redis; reading Postgres")
            return current, counts
        mapping_date = self._resolver.mapping_date_for(as_of)
        if mapping_date is None:
            raise RequestError(f"nothing had been mapped on or before {as_of}", 404)
        logger.info(f"answering for past date {as_of} (mapping date {mapping_date}) from Postgres")
        return mapping_date, None

    def segments(self):
        """
        Every segment mapped on the current date, with its shape, identity fields and instrument count.
        """
        mapping_date, counts = self.mapping_date()
        if counts is None:
            with self.engine.connect() as connection:
                rows = connection.execute(text(
                    f"SELECT m.segment, count(*) AS instruments FROM {tables.MASTER} m "
                    f"WHERE {_mapped_on()} GROUP BY m.segment"), {"mapping_date": mapping_date}).all()
            counts = {row.segment: row.instruments for row in rows}

        segments = []
        for segment in sorted(counts, key=_segment_order):
            exchange, bare = split_segment_value(segment)
            if segment == UNCATEGORISED:
                exchange, bare = "unknown", UNCATEGORISED
            shape = shape_of(segment)
            segments.append({
                "exchange": exchange,
                "segment": segment,
                "bare_segment": bare,
                "shape": shape,
                "identity_fields": list(IDENTITY_FIELDS[shape]),
                "instruments": counts[segment],
            })
        exchanges = sorted({entry["exchange"] for entry in segments}, key=lambda name: (name == "unknown", name))
        return {"mapping_date": mapping_date.isoformat(), "exchanges": exchanges, "segments": segments}

    def master(self, exchange, segment, as_of=None):
        """
        Every instrument in a scope mapped on a date, as a mapping date and a generator of identities.

        The generator reads at most one batch at a time, so a listing of the whole universe never holds it.

        - `exchange` is an exchange, or `all`.
        - `segment` is an exchange-prefixed segment, or `all`.
        - `as_of` is the date asked about, or None for today.
        """
        mapping_date, counts = self.mapping_date(as_of)
        if counts is not None:
            return mapping_date, self._master_from_cache(mapping_date, counts, exchange, segment)
        return mapping_date, self._master_from_postgres(mapping_date, exchange, segment)

    def _in_scope(self, segments, exchange, segment):
        """
        The segments of a listing's scope, in canonical order.

        - `segments` are the segments that exist.
        - `exchange` is an exchange, or `all`.
        - `segment` is an exchange-prefixed segment, or `all`.
        """
        chosen = []
        for candidate in segments:
            if segment != "all" and candidate != segment:
                continue
            candidate_exchange = "unknown" if candidate == UNCATEGORISED else split_segment_value(candidate)[0]
            if exchange != "all" and candidate_exchange != exchange:
                continue
            chosen.append(candidate)
        return sorted(chosen, key=_segment_order)

    def _master_from_cache(self, mapping_date, counts, exchange, segment):
        """
        Stream a listing out of the catalogue sets and the identity hash.
        """
        for scoped in self._in_scope(counts, exchange, segment):
            for start in range(0, counts[scoped], BATCH):
                identifiers = self.redis.read_catalogue(mapping_date, scoped, start, start + BATCH - 1)
                if identifiers is None:
                    logger.error(f"Redis became unreachable while listing {scoped}; the listing is incomplete")
                    return
                identities = self.redis.read_identities(mapping_date, identifiers)
                for identifier in identifiers:
                    identity = identities.get(identifier)
                    if identity is not None:
                        yield identity_to_json(identity)

    def _master_from_postgres(self, mapping_date, exchange, segment):
        """
        Stream a listing out of the instrument table, for a past date or a cold cache.
        """
        conditions = [_mapped_on()]
        parameters = {"mapping_date": mapping_date}
        if segment != "all":
            conditions.append("m.segment = :segment")
            parameters["segment"] = segment
        if exchange != "all":
            conditions.append("m.exchange = :exchange")
            parameters["exchange"] = exchange
        statement = text(f"SELECT {_IDENTITY_COLUMNS} FROM {tables.MASTER} m "
                         f"WHERE {' AND '.join(conditions)} ORDER BY {_LISTING_ORDER}")
        with self.engine.connect().execution_options(stream_results=True, max_row_buffer=BATCH) as connection:
            for row in connection.execute(statement, parameters):
                yield identity_to_json(row._mapping)

    def search(self, exchange, segment, query, as_of=None, limit=50):
        """
        Instruments in one segment whose symbol or underlying contains a term.

        Exact name matches come first, then names starting with the term, then names containing it;
        contracts under one name follow in expiry, strike and option type order.

        - `exchange` is the exchange.
        - `segment` is the exchange-prefixed segment.
        - `query` is the term, or empty for the segment's first instruments.
        - `as_of` is the date asked about, or None for today.
        - `limit` is the most instruments to return.
        """
        mapping_date, counts = self.mapping_date(as_of)
        term = (query or "").strip().upper()
        if counts is not None:
            instruments = self._search_cache(mapping_date, segment, term, limit)
        else:
            instruments = self._search_postgres(mapping_date, exchange, segment, term, limit)
        return {"mapping_date": mapping_date.isoformat(), "instruments": instruments}

    def _search_cache(self, mapping_date, segment, term, limit):
        """
        Search a segment's names set, then take each matching name's contracts from its catalogue.
        """
        names = self.redis.read_names(mapping_date, segment)
        if names is None:
            raise RequestError("the instrument cache is unreachable", 503)
        matches = [name for name in names if term in name]
        matches.sort(key=lambda name: (name != term, not name.startswith(term), name))

        identifiers = []
        for name in matches:
            found = self.redis.read_catalogue_for_prefix(mapping_date, segment, self.redis.catalogue_prefix(name),
                                                         limit - len(identifiers))
            identifiers.extend(found or [])
            if len(identifiers) >= limit:
                break
        identities = self.redis.read_identities(mapping_date, identifiers)
        return [identity_to_json(identities[identifier]) for identifier in identifiers if identifier in identities]

    def _search_postgres(self, mapping_date, exchange, segment, term, limit):
        """
        Search the instrument table, for a past date or a cold cache.
        """
        statement = text(
            f"SELECT {_IDENTITY_COLUMNS} FROM {tables.MASTER} m "
            f"WHERE m.segment = :segment AND m.exchange = :exchange AND {_NAME} LIKE :pattern ESCAPE '\\' "
            f"  AND {_mapped_on()} "
            f"ORDER BY {_NAME} <> :term, {_NAME} NOT LIKE :prefix ESCAPE '\\', {_LISTING_ORDER} "
            f"LIMIT :limit")
        escaped = _escape_like(term)
        with self.engine.connect() as connection:
            rows = connection.execute(statement, {
                "segment": segment, "exchange": exchange, "term": term, "limit": limit,
                "pattern": f"%{escaped}%", "prefix": f"{escaped}%", "mapping_date": mapping_date,
            }).all()
        return [identity_to_json(row._mapping) for row in rows]

    def resolve(self, instrument, as_of=None, mapped_only=True):
        """
        The identity of the instrument a request names, with the mapping date and whether it came from the cache.

        Returns a tuple `(identity, mapping_date, cached)`, where `identity` is an identity dict.

        - `instrument` is the `InstrumentQuery` the request parsed to.
        - `as_of` is the date asked about, or None for today.
        - `mapped_only` requires the instrument to be mapped on that date. History endpoints pass False,
          so an expired contract or a delisted stock is still found in the instrument table.
        """
        mapping_date, resolutions = self.resolve_many([instrument], as_of, mapped_only)
        resolution = resolutions[0]
        if isinstance(resolution, RequestError):
            raise resolution
        identity, cached = resolution
        return identity, mapping_date, cached

    def resolve_many(self, instruments, as_of=None, mapped_only=True):
        """
        The identities of several instruments, resolved together on one mapping date.

        Instruments named by id are read with one HMGET, and instruments named by their identity fields are found with one pipeline of catalogue look-ups, so a list costs the same Redis round trips as one instrument. An instrument the cache cannot answer for is looked up in Postgres on its own, which happens only for a past date, a cold cache, or the history of an instrument no longer mapped.

        Args:
            instruments (list[InstrumentQuery]): The instruments the request named, in order.
            as_of (datetime.date | None): The date asked about, or None for today.
            mapped_only (bool): Whether each instrument must be mapped on that date. History endpoints pass False, so an expired contract or a delisted stock is still found in the instrument table.

        Returns:
            tuple: A pair (mapping_date, resolutions), where mapping_date is the datetime.date answered on and resolutions holds one entry per instrument in order: a pair (identity, cached) of the identity dict and whether it came from the cache, or the RequestError saying why that instrument was not found.

        Raises:
            RequestError: When nothing has been mapped yet, or nothing had been mapped on or before as_of.
        """
        mapping_date, counts = self.mapping_date(as_of)
        if counts is not None:
            cached_identities = self._resolve_many_from_cache(mapping_date, instruments)
        else:
            cached_identities = [None] * len(instruments)

        resolutions = []
        for position, instrument in enumerate(instruments):
            identity = cached_identities[position]
            if identity is not None:
                resolutions.append((identity, True))
                continue
            if counts is not None:
                if mapped_only:
                    resolutions.append(RequestError(self._not_found(instrument, mapping_date), 404))
                    continue
                logger.info(f"instrument not in today's cache; looking for its history in {tables.MASTER}")
            identity = self._resolve_from_postgres(mapping_date, instrument, mapped_only)
            if identity is None:
                message = self._not_found(instrument, mapping_date if mapped_only else None)
                resolutions.append(RequestError(message, 404))
            else:
                resolutions.append((identity, False))
        return mapping_date, resolutions

    def _resolve_many_from_cache(self, mapping_date, instruments):
        """
        Find several instruments in the cache, by id or by their catalogue members.

        Args:
            mapping_date (datetime.date): The mapping date the cache holds.
            instruments (list[InstrumentQuery]): The instruments the request named, in order.

        Returns:
            list[dict | None]: One identity per instrument in order, or None where the cache does not hold it.
        """
        identifiers = []
        segment_prefixes = []
        prefix_positions = []
        for position, instrument in enumerate(instruments):
            identifiers.append(instrument.instrument_id)
            if instrument.instrument_id is None:
                prefix = self.redis.catalogue_prefix(instrument.name, instrument.fields.get("expiry_date"),
                                                     instrument.fields.get("strike_price"),
                                                     instrument.fields.get("option_type"))
                segment_prefixes.append((instrument.segment, prefix))
                prefix_positions.append(position)

        if segment_prefixes:
            found = self.redis.read_catalogue_for_prefixes(mapping_date, segment_prefixes)
            if found is not None:
                for index, position in enumerate(prefix_positions):
                    identifiers[position] = found[index]

        wanted = []
        for identifier in identifiers:
            if identifier is not None:
                wanted.append(identifier)
        identities = {}
        if wanted:
            identities = self.redis.read_identities(mapping_date, wanted)

        cached_identities = []
        for identifier in identifiers:
            if identifier is None:
                cached_identities.append(None)
            else:
                cached_identities.append(identities.get(identifier))
        return cached_identities

    def _resolve_from_postgres(self, mapping_date, instrument, mapped_only):
        """
        Find an instrument in the instrument table by id, or by segment and identity fields.
        """
        if instrument.instrument_id is not None:
            conditions = ["m.instrument_id = CAST(:instrument_id AS uuid)"]
            parameters = {"instrument_id": instrument.instrument_id}
        else:
            conditions = ["m.segment = :segment", "m.exchange = :exchange", f"{_NAME} = :name"]
            parameters = {"segment": instrument.segment, "exchange": instrument.exchange, "name": instrument.name}
            for field in ("expiry_date", "strike_price", "option_type"):
                if field in instrument.fields:
                    conditions.append(f"m.{field} = :{field}")
                    parameters[field] = instrument.fields[field]
        if mapped_only:
            conditions.append(_mapped_on())
            parameters["mapping_date"] = mapping_date
        with self.engine.connect() as connection:
            row = connection.execute(text(
                f"SELECT {_IDENTITY_COLUMNS}, m.first_seen_date, m.last_seen_date FROM {tables.MASTER} m "
                f"WHERE {' AND '.join(conditions)} LIMIT 1"), parameters).first()
        return dict(row._mapping) if row is not None else None

    def _not_found(self, instrument, mapping_date):
        """
        The message for an instrument that could not be found.
        """
        described = instrument.instrument_id or " ".join(
            str(value) for value in [instrument.segment, *instrument.fields.values()])
        if mapping_date is None:
            return f"no instrument {described}"
        return f"no instrument {described} is mapped on {mapping_date}"

    def details(self, instrument, as_of=None):
        """
        One instrument's identity, the dates it was seen, its lot and tick size, and every broker's handle on the mapping date.

        `lot_size` is underlying units per lot, decided as the unified quote decides it: 1 for a security, Groww's figure on MCX, and the brokers' majority elsewhere. `tick_size` is in rupees, the value most brokers agree on. Each is null when the brokers tie or none sends one. The handles in `carried_by` keep each broker's own lot size, because an order's quantity is checked against the broker it goes to.

        - `instrument` is the `InstrumentQuery` the request parsed to.
        - `as_of` is the date asked about, or None for today.
        """
        answer = self.details_many([instrument], as_of)[0]
        if isinstance(answer, RequestError):
            raise answer
        return answer

    def details_many(self, instruments, as_of=None):
        """
        Several instruments' details, as details gives them, read together.

        The seen dates and handles of every instrument found in the cache are read with one HMGET each, whatever the number of instruments. An instrument answered from Postgres has its broker rows read on its own.

        Args:
            instruments (list[InstrumentQuery]): The instruments the request named, in order.
            as_of (datetime.date | None): The date asked about, or None for today.

        Returns:
            list: One entry per instrument in order: the details dict, or the RequestError saying why that instrument was not found.

        Raises:
            RequestError: When nothing has been mapped yet, or nothing had been mapped on or before as_of.
        """
        mapping_date, resolutions = self.resolve_many(instruments, as_of)
        cached_identifiers = []
        for resolution in resolutions:
            if isinstance(resolution, RequestError):
                continue
            identity, cached = resolution
            if cached:
                cached_identifiers.append(str(identity["instrument_id"]))
        seen_by_instrument = self.redis.read_seen(mapping_date, cached_identifiers)
        handles_by_instrument = self.redis.read_order_handles(mapping_date, cached_identifiers)

        answers = []
        for resolution in resolutions:
            if isinstance(resolution, RequestError):
                answers.append(resolution)
                continue
            identity, cached = resolution
            identifier = str(identity["instrument_id"])
            if cached:
                first_seen, last_seen = seen_by_instrument.get(identifier, (None, None))
                handles = handles_by_instrument.get(identifier, {})
                carried_by = [{"broker": broker, **handles[broker]} for broker in sorted(handles)]
            else:
                first_seen, last_seen = identity.get("first_seen_date"), identity.get("last_seen_date")
                carried_by = [{key: row[key] for key in ("broker", "broker_token", "order_symbol")}
                              | {"lot_size": None if row["lot_size"] is None else str(row["lot_size"]),
                                 "tick_size": None if row["tick_size"] is None else str(row["tick_size"])}
                              for row in self._resolver.broker_rows_on_date(identifier, mapping_date)]
            answers.append(self._details_answer(identity, mapping_date, first_seen, last_seen, carried_by))
        return answers

    def _details_answer(self, identity, mapping_date, first_seen, last_seen, carried_by):
        """
        One instrument's details answer, from what was read for it.

        Args:
            identity (dict): The instrument's identity.
            mapping_date (datetime.date): The mapping date answered on.
            first_seen (datetime.date | None): The first date the instrument was mapped.
            last_seen (datetime.date | None): The last date the instrument was mapped.
            carried_by (list[dict]): Each broker's handle, with its broker name, in broker order.

        Returns:
            dict: The details, as the `/details` route sends them.
        """
        handles_by_broker = {}
        for handle in carried_by:
            handles_by_broker[handle["broker"]] = handle
        lot_size, _ = units_per_lot(identity, handles_by_broker)
        return {
            **identity_to_json(identity),
            "mapping_date": mapping_date.isoformat(),
            "first_seen_date": first_seen.isoformat() if first_seen else None,
            "last_seen_date": last_seen.isoformat() if last_seen else None,
            "lot_size": lot_size,
            "tick_size": self.agreed_tick_size(carried_by),
            "carried_by": carried_by,
        }

    def additional_details(self, instrument, as_of=None):
        """
        One instrument's identity and the extra attributes each broker's own instrument file carries.

        These are the columns a broker publishes beyond the handle an order needs: the ISIN, the series, the freeze quantity, the price band, the multiplier and so on. Every broker's spellings are given one shared set of names by `stock_brokers/instruments/mapping/utilities/raw_attributes.py`, so an ISIN reads as `isin` whether the broker called it `isin`, `pisin` or `isin_code`, and every name is present for every broker with None where that broker publishes nothing.

        The attributes are read from the same Redis tier `/details` reads, warmed by the same daily run, and fall back to the mapping table for a past date or a cold cache exactly as the rest of the catalogue does.

        - `instrument` is the `InstrumentQuery` the request parsed to.
        - `as_of` is the date asked about, or None for today.
        """
        answer = self.additional_details_many([instrument], as_of)[0]
        if isinstance(answer, RequestError):
            raise answer
        return answer

    def additional_details_many(self, instruments, as_of=None):
        """
        Several instruments' additional attributes, as additional_details gives them, read together.

        The attributes of every instrument found in the cache are read with one HMGET. When some came back empty, one EXISTS tells an instrument whose brokers publish nothing apart from a hash that was never warmed; in the second case those instruments join the ones answered from Postgres, which are read with one query.

        Args:
            instruments (list[InstrumentQuery]): The instruments the request named, in order.
            as_of (datetime.date | None): The date asked about, or None for today.

        Returns:
            list: One entry per instrument in order: the additional details dict, or the RequestError saying why that instrument was not found.

        Raises:
            RequestError: When nothing has been mapped yet, or nothing had been mapped on or before as_of.
        """
        mapping_date, resolutions = self.resolve_many(instruments, as_of)
        cached_identifiers = []
        uncached_identifiers = []
        for resolution in resolutions:
            if isinstance(resolution, RequestError):
                continue
            identity, cached = resolution
            if cached:
                cached_identifiers.append(str(identity["instrument_id"]))
            else:
                uncached_identifiers.append(str(identity["instrument_id"]))

        attributes_by_instrument = {}
        if cached_identifiers:
            attributes_by_instrument = self.redis.read_additional_attributes(mapping_date, cached_identifiers)
            missing = []
            for identifier in cached_identifiers:
                if identifier not in attributes_by_instrument:
                    missing.append(identifier)
            if missing and not self.redis.has_additional_attributes(mapping_date):
                logger.warning(f"the additional attributes for {mapping_date} are not in Redis; reading Postgres")
                uncached_identifiers.extend(missing)
        if uncached_identifiers:
            attributes_by_instrument.update(self.cache.postgres_tier.read_additional_attributes(
                mapping_date, uncached_identifiers))

        answers = []
        for resolution in resolutions:
            if isinstance(resolution, RequestError):
                answers.append(resolution)
                continue
            identity, _ = resolution
            attributes_by_broker = attributes_by_instrument.get(str(identity["instrument_id"]), {})
            carried_by = []
            for broker in sorted(attributes_by_broker):
                entry = {"broker": broker}
                entry.update(self._raw_attributes.fill(attributes_by_broker[broker]))
                carried_by.append(entry)
            answers.append({
                **identity_to_json(identity),
                "mapping_date": mapping_date.isoformat(),
                "attribute_names": list(ATTRIBUTE_NAMES),
                "carried_by": carried_by,
            })
        return answers

    @staticmethod
    def agreed_tick_size(handles):
        """Finds the tick size most of an instrument's brokers agree on.

        Args:
            handles (Iterable[dict]): Every broker's handle on the instrument, each with a "tick_size" that is a string in rupees or None.

        Returns:
            str | None: The most common positive tick size, written without an exponent, or None when no broker sends one or the two most common values are equally common.
        """
        tick_sizes = Counter()
        for handle in handles:
            try:
                tick_size = Decimal(str(handle.get("tick_size")))
            except (InvalidOperation, ValueError):
                continue
            if tick_size.is_finite() and tick_size > 0:
                tick_sizes[tick_size] += 1
        ranked = tick_sizes.most_common(2)
        if not ranked:
            return None
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            return None
        return format(ranked[0][0].normalize(), "f")
