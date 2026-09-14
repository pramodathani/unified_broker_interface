"""
The instrument universe as the REST API sees it: segments, listings, search, details and resolving a
request to one instrument.

Everything is answered from the Redis tier of the instrument mapping cache, which the daily warm fills
for the current mapping date: the identity and order handle hashes, and the catalogue it builds for
browsing and searching - one sorted set per segment in name, expiry, strike and option type order, a
set of each segment's distinct names, each instrument's first and last seen dates, and a count per
segment. See `stock_brokers/instruments/mapping/utilities/cache.py`.

The tables are the unified ones, `unified.instruments` and `unified.broker_mappings`, which `bin/unified/map_instruments`
maps and warms the cache from; every query here names its tables through
`stock_brokers.instruments.mapping.utilities.tables`. TimescaleDB is read only when the cache cannot answer, and each time it is, it is logged:

- **a past date** - the cache holds only the current mapping date, by design, so a `date` before it
  is answered from the instrument and broker mapping tables;
- **a cold cache** - the date's catalogue has not been warmed, because Redis was flushed or the
  midnight expiry passed before the morning warm;
- **history of an instrument no longer mapped** - an expired contract or a delisted stock is absent
  from today's cache but still has prices, so `/prices` and `/ticks` look it up in the instrument table.
"""

from sqlalchemy import text

from stock_brokers.instruments.mapping.utilities import tables
from stock_brokers.instruments.mapping.utilities.resolution import MappingResolver
from stock_brokers.instruments.mapping.utilities.segments import segment_rank, split_segment_value
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
        mapping_date, counts = self.mapping_date(as_of)
        if counts is not None:
            identity = self._resolve_from_cache(mapping_date, instrument)
            if identity is not None:
                return identity, mapping_date, True
            if mapped_only:
                raise RequestError(self._not_found(instrument, mapping_date), 404)
            logger.info(f"instrument not in today's cache; looking for its history in {tables.MASTER}")

        identity = self._resolve_from_postgres(mapping_date, instrument, mapped_only)
        if identity is None:
            raise RequestError(self._not_found(instrument, mapping_date if mapped_only else None), 404)
        return identity, mapping_date, False

    def _resolve_from_cache(self, mapping_date, instrument):
        """
        Find an instrument in the cache by id, or by its catalogue member.
        """
        identifier = instrument.instrument_id
        if identifier is None:
            prefix = self.redis.catalogue_prefix(instrument.name, instrument.fields.get("expiry_date"),
                                                 instrument.fields.get("strike_price"),
                                                 instrument.fields.get("option_type"))
            found = self.redis.read_catalogue_for_prefix(mapping_date, instrument.segment, prefix, 1)
            if not found:
                return None
            identifier = found[0]
        return self.redis.read_identities(mapping_date, [identifier]).get(identifier)

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
        One instrument's identity, the dates it was seen, and every broker's handle on the mapping date.

        - `instrument` is the `InstrumentQuery` the request parsed to.
        - `as_of` is the date asked about, or None for today.
        """
        identity, mapping_date, cached = self.resolve(instrument, as_of)
        identifier = str(identity["instrument_id"])
        if cached:
            first_seen, last_seen = self.redis.read_seen(mapping_date, [identifier]).get(identifier, (None, None))
            handles = self.redis.read_order_handles(mapping_date, [identifier]).get(identifier, {})
            carried_by = [{"broker": broker, **handles[broker]} for broker in sorted(handles)]
        else:
            first_seen, last_seen = identity.get("first_seen_date"), identity.get("last_seen_date")
            carried_by = [{key: row[key] for key in ("broker", "broker_token", "order_symbol")}
                          | {"lot_size": None if row["lot_size"] is None else str(row["lot_size"]),
                             "tick_size": None if row["tick_size"] is None else str(row["tick_size"])}
                          for row in self._resolver.broker_rows_on_date(identifier, mapping_date)]
        return {
            **identity_to_json(identity),
            "mapping_date": mapping_date.isoformat(),
            "first_seen_date": first_seen.isoformat() if first_seen else None,
            "last_seen_date": last_seen.isoformat() if last_seen else None,
            "carried_by": carried_by,
        }
