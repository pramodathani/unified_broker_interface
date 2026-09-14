"""
Look-ups over the mapped instrument tables.

Three questions can be asked, and between them they close the loop from an instrument identity to a broker's own raw row and back:

- ``broker_tokens`` goes from an identity to every broker's token for it, which is what placing an order or requesting a quote needs.
- ``identity`` goes the other way, from a broker's tokens back to the unified identities, which is what reading a position or holding back from a broker needs.
- ``raw_row`` goes from a broker token to that broker's full raw row, which is the escape hatch for anything the mapped tables do not carry.

The third exists because a broker's own quote endpoint sometimes needs an identifier the mapped tables have no column for. Because ``broker_token`` is each broker's own join key into its raw table, that row is always one lookup away.

Placing an order is not such a case. The ``broker_symbol`` column is a display name for several brokers rather than a tradeable ticker, so ``unified.broker_mappings`` carries ``order_symbol`` beside it, filled from each broker's own tradeable column for the six brokers that order by symbol and left empty for the four that order by token alone. An order therefore reads a column rather than reconstructing a ticker from a raw row.

Two further look-ups exist for the case where a broker reports a position without a token at all. ``identity_by_isin`` identifies an instrument from its ISIN, which is the only identifier a Groww holding carries, and ``identity_by_symbol`` identifies one from its ticker.

Every method takes an ``as_of_date`` and uses the latest mapping on or before it, so a lookup for a past date sees what was mapped then rather than what is mapped now.

A lookup that lands on the current mapping date is answered through the ``MappingCache`` the resolver holds, which keeps it out of the database; one for an earlier date goes straight to Postgres and caches nothing.

The resolver is handed a cache rather than building one. The memory tier only pays for itself when a process has exactly one of it, so a resolver that made its own would give a process two sets of dictionaries, double the memory and halve the hit rate.
"""

import pandas as pd
from sqlalchemy import text

from stock_brokers.instruments.mapping.utilities.segments import MAPPED_BROKERS
from stock_brokers.instruments.mapping.utilities.cache import MappingCache
from stock_brokers.instruments.mapping.base import instrument_id
from stock_brokers.instruments.mapping.utilities import tables

RAW_TOKEN_COLUMNS = {
    "dhan": "security_id",
    "kotak": "psymbol",
    "groww": "exchange_token",
    "stoxkart": "token",
    "fyers": "fytoken",
    "wisdom_capital": "exchangeinstrumentid",
    "indmoney": "security_id",
    "flattrade": "token",
    "shoonya": "token",
    "zerodha": "instrument_token",
}

ISIN_COLUMNS = [
    ("dhan", "isin"),
    ("kotak", "pisin"),
    ("groww", "isin"),
    ("stoxkart", "isin_code"),
    ("fyers", "isin"),
    ("wisdom_capital", "isin"),
    ("indmoney", "isin"),
]


class MappingResolver:
    """
    Every look-up over the mapped instrument tables, cached where the date allows it and read from Postgres where it does not.

    Attributes:
        mapping_cache (MappingCache): The cache a request for the current date is answered from.
        engine (sqlalchemy.engine.Engine): The SQLAlchemy engine over TimescaleDB.
    """

    def __init__(self, mapping_cache=None):
        """
        Build the resolver around a cache.

        Args:
            mapping_cache (MappingCache | None): The cache to answer current-date requests from. None builds one, which is right for a command line tool and wrong for anything sharing a process with another resolver.

        Returns:
            None: This function returns nothing.
        """
        self.mapping_cache = mapping_cache or MappingCache()
        self.engine = self.mapping_cache.engine

    def mapping_date_for(self, as_of_date):
        """
        The mapping date a request for one as-of date resolves to.

        The current date comes from the cache, which reads it from a small Redis key rather than computing it, because a max over the whole hypertable costs about 1.2 seconds and has no selective filter of its own. Only a request for an earlier date pays that max, and it pays a filtered one.

        Args:
            as_of_date (datetime.date): The date the caller asked about.

        Returns:
            datetime.date | None: The latest mapping date on or before as_of_date, or None when nothing was mapped by then.
        """
        current = self.mapping_cache.resolves_to_current_date(as_of_date)
        if current is not None:
            return current
        with self.engine.connect() as connection:
            return connection.execute(
                text(
                    f"SELECT max(mapping_date) FROM {tables.BROKER_MAPPINGS} "
                    "WHERE mapping_date <= :as_of_date"
                ),
                {
                    "as_of_date": as_of_date,
                },
            ).scalar()

    def broker_tokens(self, exchange, segment, shape, identity, as_of_date):
        """
        Find every broker's token for one instrument identity.

        Args:
            exchange (str): Canonical lowercase exchange name, for example "nse".
            segment (str): Exchange-prefixed segment value, for example "nse_equities".
            shape (str): One of "security", "future", or "option".
            identity (dict): The identity fields for the shape, for example {"symbol": "RELIANCE"}.
            as_of_date (datetime.date): Use the latest mapping on or before this date.

        Returns:
            tuple: A (mapping_date, rows) pair, where mapping_date is the date the answer came from (datetime.date, or None when the instrument was never mapped) and rows is a list of dicts with keys "broker", "broker_token", "broker_symbol", "order_symbol", "lot_size", and "tick_size".
        """
        computed_id = instrument_id(exchange, segment, shape, identity)

        mapping_date = self.mapping_cache.resolves_to_current_date(as_of_date)
        rows = []
        if mapping_date is not None:
            rows = self.broker_rows_on_date(computed_id, mapping_date)
        if rows:
            return (mapping_date, rows)

        with self.engine.connect() as connection:
            latest = connection.execute(
                text(
                    f"SELECT max(mapping_date) AS mapping_date FROM {tables.BROKER_MAPPINGS} "
                    "WHERE instrument_id = :instrument_id AND mapping_date <= :as_of_date"
                ),
                {
                    "instrument_id": computed_id,
                    "as_of_date": as_of_date,
                },
            ).one()
            mapping_date = latest.mapping_date
        if mapping_date is None:
            return (None, [])

        return (mapping_date, self.broker_rows_on_date(computed_id, mapping_date))

    def broker_rows_on_date(self, computed_id, mapping_date):
        """
        Read one instrument's broker rows for one exact mapping date.

        Args:
            computed_id (str): The instrument id.
            mapping_date (datetime.date): The mapping date to read.

        Returns:
            list[dict]: One dict per broker, with keys "broker", "broker_token", "broker_symbol", "order_symbol", "lot_size", and "tick_size", ordered by broker.
        """
        with self.engine.connect() as connection:
            result = connection.execute(
                text(
                    "SELECT broker, broker_token, broker_symbol, order_symbol, lot_size, tick_size "
                    f"FROM {tables.BROKER_MAPPINGS} "
                    "WHERE instrument_id = :instrument_id AND mapping_date = :mapping_date "
                    "ORDER BY broker"
                ),
                {
                    "instrument_id": computed_id,
                    "mapping_date": mapping_date,
                },
            ).all()

        rows = []
        for row in result:
            rows.append(
                {
                    "broker": row.broker,
                    "broker_token": row.broker_token,
                    "broker_symbol": row.broker_symbol,
                    "order_symbol": row.order_symbol,
                    "lot_size": row.lot_size,
                    "tick_size": row.tick_size,
                }
            )
        return rows

    def identity(self, broker, broker_tokens, as_of_date, segments=None):
        """
        Find the unified identity behind each of one broker's tokens.

        A token can point at more than one instrument, which happens when a broker's file reuses it, so the most recent mapping wins and the symbol breaks any remaining tie. That keeps the answer stable from one call to the next rather than depending on row order.

        The tie-break alone is not enough when the caller already knows what kind of instrument it is holding, because the winning symbol can be the wrong one. Zerodha's BSE token 128224004 carries both ITC in bse_equities and a spurious ISIN-shaped row in bse_fixed_income, and the alphabetical tie-break prefers the latter. Passing the segments a holding can possibly be in removes the twin from consideration rather than hoping the tie-break lands on the right row.

        Args:
            broker (str): The broker name, for example "zerodha".
            broker_tokens (list[str]): The broker's own tokens to resolve.
            as_of_date (datetime.date): Use the latest mapping on or before this date.
            segments (list[str] | None): Canonical segment names to restrict the answer to, for example ["nse_equities", "bse_equities"], or None to accept any segment.

        Returns:
            dict: Mapping of broker token to a dict with keys "instrument_id", "exchange", "segment", "shape", "symbol", "underlying_symbol", "expiry_date", "strike_price", "option_type", and "mapping_date". Tokens with no mapping, and tokens whose only mappings fall outside the requested segments, are absent from the result.
        """
        if not broker_tokens:
            return {}

        tokens = []
        for token in broker_tokens:
            tokens.append(str(token))

        if self.mapping_cache.resolves_to_current_date(as_of_date) is not None:
            return self.mapping_cache.identities_for_tokens(broker, tokens, as_of_date, segments)

        statement = (
            "SELECT DISTINCT ON (b.broker_token) "
            "  b.broker_token, b.mapping_date, m.instrument_id, m.exchange, m.segment, m.shape, "
            "  m.symbol, m.underlying_symbol, m.expiry_date, m.strike_price, m.option_type "
            f"FROM {tables.BROKER_MAPPINGS} b "
            f"JOIN {tables.MASTER} m ON m.instrument_id = b.instrument_id "
            "WHERE b.broker = :broker AND b.mapping_date <= :as_of_date "
            "  AND b.broker_token = ANY(:tokens) "
        )
        parameters = {
            "broker": broker,
            "as_of_date": as_of_date,
            "tokens": tokens,
        }
        if segments is not None:
            statement = statement + "  AND m.segment = ANY(:segments) "
            parameters["segments"] = list(segments)
        statement = statement + "ORDER BY b.broker_token, b.mapping_date DESC, m.symbol ASC, m.instrument_id ASC"

        with self.engine.connect() as connection:
            result = connection.execute(text(statement), parameters).all()

        resolved = {}
        for row in result:
            resolved[row.broker_token] = {
                "instrument_id": str(row.instrument_id),
                "exchange": row.exchange,
                "segment": row.segment,
                "shape": row.shape,
                "symbol": row.symbol,
                "underlying_symbol": row.underlying_symbol,
                "expiry_date": row.expiry_date,
                "strike_price": row.strike_price,
                "option_type": row.option_type,
                "mapping_date": row.mapping_date,
            }
        return resolved

    def identity_spans(self, broker, broker_tokens, segments=None, match_on="broker_token"):
        """
        Find every instrument each of one broker's tokens has pointed at, over every mapping date.

        ``identity`` answers for one date, which suits a live position and does not suit a stored price series. A series holds bars from years before the first mapping date, and its token can have pointed at different instruments across the mapping dates there are - a symbol change, a move from EQ to BE, a day on which the broker's file filed a row under the wrong segment. So this returns all of them, each with the span of dates it was seen on, and leaves the choice between them to the caller, who knows what the series is.

        Args:
            broker (str): The broker name, for example "flattrade".
            broker_tokens (list[str]): The values to look up.
            segments (list[str] | None): Canonical segment names to restrict the answer to, or None to accept any segment.
            match_on (str): The broker_mappings column the values are compared with, "broker_token" or "order_symbol". Fyers stores its price series under its ticker, which the mapping keeps as order_symbol.

        Returns:
            dict: Mapping of each value to a list of dicts with keys "instrument_id", "exchange", "segment", "shape", "symbol", "first_mapping_date", "last_mapping_date" and "mapping_dates", ordered by first_mapping_date. Values with no mapping in the requested segments are absent.
        """
        if not broker_tokens:
            return {}
        if match_on not in ("broker_token", "order_symbol"):
            raise ValueError(f"cannot match broker_mappings on {match_on!r}")

        tokens = []
        for token in broker_tokens:
            tokens.append(str(token))

        statement = (
            f"SELECT b.{match_on} AS broker_token, m.instrument_id, m.exchange, m.segment, m.shape, m.symbol, "
            "  min(b.mapping_date) AS first_mapping_date, max(b.mapping_date) AS last_mapping_date, "
            "  count(*) AS mapping_dates "
            f"FROM {tables.BROKER_MAPPINGS} b "
            f"JOIN {tables.MASTER} m ON m.instrument_id = b.instrument_id "
            f"WHERE b.broker = :broker AND b.{match_on} = ANY(:tokens) "
        )
        parameters = {
            "broker": broker,
            "tokens": tokens,
        }
        if segments is not None:
            statement = statement + "  AND m.segment = ANY(:segments) "
            parameters["segments"] = list(segments)
        statement = statement + (
            f"GROUP BY b.{match_on}, m.instrument_id, m.exchange, m.segment, m.shape, m.symbol "
            f"ORDER BY b.{match_on}, first_mapping_date, m.instrument_id"
        )

        with self.engine.connect() as connection:
            result = connection.execute(text(statement), parameters).all()

        spans = {}
        for row in result:
            spans.setdefault(row.broker_token, []).append({
                "instrument_id": str(row.instrument_id),
                "exchange": row.exchange,
                "segment": row.segment,
                "shape": row.shape,
                "symbol": row.symbol,
                "first_mapping_date": row.first_mapping_date,
                "last_mapping_date": row.last_mapping_date,
                "mapping_dates": row.mapping_dates,
            })
        return spans

    def identity_by_isin(self, isin_codes, as_of_date, preferred_exchange=None):
        """
        Find the unified identities behind ISIN codes, by way of the brokers whose raw files carry an ISIN.

        This is load-bearing rather than a fallback. Groww's holdings rows publish no broker token at all, only an ISIN and a trading symbol, so an ISIN is the only identifier a Groww holding arrives with. Seven brokers publish an ISIN column, and looking one up in any of their raw files yields that broker's own token, which resolves like any other token.

        The token taken from each raw file is the broker's join key into unified.broker_mappings, which is not always the column an ISIN sits beside. Fyers is the case that matters: its ISIN sits with scrip_code while its stored token is fytoken, so taking the exchange-assigned security id here would silently find nothing.

        An answer is a list rather than one identity, because a dual listed security legitimately has both an NSE and a BSE identity and neither is wrong. The list is ordered with the preferred exchange first so that a caller with a preference does not have to re-sort it.

        Args:
            isin_codes (list[str]): The ISIN codes to resolve.
            as_of_date (datetime.date): Use the latest mapping on or before this date.
            preferred_exchange (str | None): Canonical lowercase exchange name to order first, for example "nse", or None to leave the order to the exchange name and symbol.

        Returns:
            dict: Mapping of ISIN code to a list of dicts, each holding the same keys identity returns plus "evidence_broker" and "evidence_token", naming the broker whose raw file carried the ISIN and the token it supplied. ISIN codes nothing maps are absent from the result.
        """
        if not isin_codes:
            return {}

        mapping_date = self.mapping_date_for(as_of_date)
        if mapping_date is None:
            return {}

        codes = []
        for isin_code in isin_codes:
            codes.append(str(isin_code).strip().upper())

        resolved = {}
        seen_instruments = {}
        for broker, isin_column in ISIN_COLUMNS:
            token_column = RAW_TOKEN_COLUMNS[broker]
            with self.engine.connect() as connection:
                rows = connection.execute(
                    text(
                        f"SELECT {token_column} AS broker_token, upper({isin_column}) AS isin_code "
                        f"FROM {broker}.instruments "
                        f"WHERE download_date = :mapping_date AND upper({isin_column}) = ANY(:codes)"
                    ),
                    {
                        "mapping_date": mapping_date,
                        "codes": codes,
                    },
                ).all()

            codes_by_token = {}
            for row in rows:
                if row.broker_token is None:
                    continue
                codes_by_token.setdefault(str(row.broker_token), set()).add(row.isin_code)
            if not codes_by_token:
                continue

            identities = self.identity(broker, list(codes_by_token), as_of_date)
            for broker_token, found_identity in identities.items():
                for isin_code in codes_by_token[broker_token]:
                    if found_identity["instrument_id"] in seen_instruments.setdefault(isin_code, set()):
                        continue
                    seen_instruments[isin_code].add(found_identity["instrument_id"])
                    found = dict(found_identity)
                    found["evidence_broker"] = broker
                    found["evidence_token"] = broker_token
                    resolved.setdefault(isin_code, []).append(found)

        for isin_code in resolved:
            resolved[isin_code].sort(key=lambda found: exchange_order(found, preferred_exchange))
        return resolved

    def identity_by_symbol(self, exchange, segments, symbols, as_of_date):
        """
        Find the unified identities behind trading symbols, within given segments.

        A ticker is a weaker identifier than a token or an ISIN, so this returns a list per symbol and never picks a winner. An ambiguous match is something the caller has to see rather than something to resolve quietly, because a misfiled position is worse than an unidentified one.

        Callers should restrict this to equities and exchange traded funds. A ticker match on a derivative can land on the wrong expiry or strike, where nothing about the answer looks wrong.

        Args:
            exchange (str): Canonical lowercase exchange name, for example "nse".
            segments (list[str]): Canonical segment names to search within, for example ["nse_equities"].
            symbols (list[str]): The trading symbols to resolve, matched case-insensitively.
            as_of_date (datetime.date): Use the mapping that was current on or before this date.

        Returns:
            dict: Mapping of the upper-cased symbol to a list of dicts holding the same keys identity returns. Symbols nothing matches are absent from the result.
        """
        if not symbols or not segments:
            return {}

        mapping_date = self.mapping_date_for(as_of_date)
        if mapping_date is None:
            return {}

        wanted = []
        for symbol in symbols:
            wanted.append(str(symbol).strip().upper())

        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT instrument_id, exchange, segment, shape, symbol, underlying_symbol, "
                    "  expiry_date, strike_price, option_type "
                    f"FROM {tables.MASTER} "
                    "WHERE exchange = :exchange AND segment = ANY(:segments) "
                    "  AND upper(symbol) = ANY(:symbols) "
                    "  AND first_seen_date <= :mapping_date AND last_seen_date >= :mapping_date "
                    "ORDER BY symbol ASC, segment ASC"
                ),
                {
                    "exchange": exchange,
                    "segments": list(segments),
                    "symbols": wanted,
                    "mapping_date": mapping_date,
                },
            ).all()

        resolved = {}
        for row in rows:
            found_identity = {
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
            resolved.setdefault(row.symbol.upper(), []).append(found_identity)
        return resolved

    def raw_row(self, broker, broker_token, as_of_date):
        """
        Fetch a broker's full raw instrument row for one of its own tokens.

        Args:
            broker (str): The broker name, which is also the schema its raw instruments table lives in.
            broker_token (str): The broker's own token, as stored in unified.broker_mappings.
            as_of_date (datetime.date): Use the latest downloaded snapshot on or before this date.

        Returns:
            dict | None: Every column of the raw row, or None when that broker's file has no such token on or before the date.

        Raises:
            ValueError: If the broker name is not one of the mapped brokers, since the name is interpolated into the table name.
        """
        if broker not in MAPPED_BROKERS:
            raise ValueError(f"{broker!r} is not one of the mapped brokers: {MAPPED_BROKERS}")

        token_column = RAW_TOKEN_COLUMNS[broker]
        with self.engine.connect() as connection:
            raw = pd.read_sql(
                text(
                    f"SELECT * FROM {broker}.instruments "
                    f"WHERE {token_column} = :token AND download_date <= :as_of_date "
                    f"ORDER BY download_date DESC LIMIT 1"
                ),
                connection,
                params={
                    "token": str(broker_token),
                    "as_of_date": as_of_date,
                },
            )
        if raw.empty:
            return None
        return raw.to_dict("records")[0]


def exchange_order(found, preferred_exchange):
    """
    The sort key that puts a preferred exchange's identity first among an ISIN's answers.

    Args:
        found (dict): One resolved identity.
        preferred_exchange (str | None): The exchange to order first, or None for no preference.

    Returns:
        tuple: A (preference, exchange, symbol) triple, where preference is 0 for the preferred exchange and 1 for every other.
    """
    preference = 1
    if preferred_exchange is not None and found["exchange"] == preferred_exchange:
        preference = 0
    return (preference, found["exchange"] or "", found["symbol"] or "")
