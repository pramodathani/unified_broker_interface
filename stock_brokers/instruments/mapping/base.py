"""
Shared base class for the per-broker mapping adapters.

Each broker has one subclass of ``BrokerMappingAdapter`` in its own module under ``stock_brokers/instruments/mapping/`` and one rules file under ``stock_brokers/instruments/mapping/utilities/rules/``. The rules sit under ``utilities/`` rather than beside the modules because a broker package here holds only ``__init__.py``, ``base.py`` and one ``<broker>.py`` per broker, so listing it answers "which brokers are implemented" and nothing else. The subclass sets ``BROKER_NAME`` and overrides methods only where the broker's raw file needs logic that equality rules cannot express.

The design: an instrument's unified identity is the composite natural key ``(exchange, segment, shape, identity fields)`` — a security is its ``symbol``, a future is its ``underlying_symbol`` and ``expiry_date``, an option adds ``strike_price`` and ``option_type``. Every adapter computes ``instrument_id`` independently as a UUID5 over that key, so the same real-world instrument from any broker converges on the same row in ``unified.instruments`` with no matching step. ISIN and broker tokens are used only as classification aids, never as merge keys.

Rows that no segment's rules match are not dropped. They land in the uncategorised catch-all segments — ``nse_uncategorised``, ``bse_uncategorised``, ``mcx_uncategorised``, ``ncdex_uncategorised``, or the unprefixed ``uncategorised`` when the exchange itself cannot be determined — so classification coverage stays measurable and the raw row stays recoverable through the broker table by broker, date, and token.
"""

import uuid
from datetime import date as date_class
from decimal import Decimal
from pathlib import Path

import pandas as pd
import yaml
from sqlalchemy import text

from stock_brokers.instruments.mapping.utilities.segments import (
    CANONICAL_EXCHANGES,
    segment_rank,
    segment_shape,
    segment_value,
)
from stock_brokers.instruments.mapping.utilities import tables
from utilities.configurations import get_postgres_engine

RULES_DIRECTORY = Path(__file__).parent / "utilities" / "rules"

IDENTITY_NAMESPACE = uuid.UUID("8d3f1b52-9c47-4e60-a1d8-2f5b7c94e021")


def divide_by_100(value):
    """
    Convert a value expressed in hundredths into its plain form, used for brokers that report prices and sizes multiplied by 100.

    Args:
        value (str | float | None): Raw value from a broker table row, or None.

    Returns:
        float | None: The value divided by 100, or None when the input is None or empty.
    """
    if value is None or pd.isna(value):
        return None
    return float(value) / 100


def divide_by_10_thousand(value):
    """
    Convert a value expressed in ten-thousandths into its plain form, used for the commodity option strikes that report a scale of four decimal places.

    Args:
        value (str | float | None): Raw value from a broker table row, or None.

    Returns:
        float | None: The value divided by 10000, or None when the input is None or empty.
    """
    if value is None or pd.isna(value):
        return None
    return float(value) / 10000


def divide_by_10_million(value):
    """
    Convert a value expressed in ten-millionths into its plain form, used for the currency and fixed income derivative segments that report strikes and ticks scaled by 10**7.

    Args:
        value (str | float | None): Raw value from a broker table row, or None.

    Returns:
        float | None: The value divided by 10000000, or None when the input is None or empty.
    """
    if value is None or pd.isna(value):
        return None
    return float(value) / 10000000


def day_month_year_date(value):
    """
    Parse a broker's ``DD-MM-YYYY`` expiry text into a date, used where the generic parser would read a day of 12 or less as a month instead.

    Args:
        value (str | float | None): Raw expiry text from a broker table row, or None.

    Returns:
        datetime.date | None: The expiry date, or None when the input is None, empty, or unparseable.
    """
    if value is None or pd.isna(value):
        return None
    try:
        return pd.to_datetime(value, format="%d-%m-%Y").date()
    except (ValueError, TypeError):
        return None


def unix_epoch_date(value):
    """
    Convert a broker's expiry timestamp expressed as seconds since the 1970 Unix epoch into a date.

    Args:
        value (str | float | None): Raw seconds value from a broker table row, or None.

    Returns:
        datetime.date | None: The expiry date, or None when the input is None or empty.
    """
    if value is None or pd.isna(value):
        return None
    return pd.to_datetime(float(value), unit="s", utc=True).date()


def day_month_name_year_date(value):
    """
    Parse a broker's ``DD-MON-YYYY`` expiry text, such as "26-SEP-2026", into a date.

    Args:
        value (str | float | None): Raw expiry text from a broker table row, or None.

    Returns:
        datetime.date | None: The expiry date, or None when the input is None, empty, or unparseable.
    """
    if value is None or pd.isna(value):
        return None
    try:
        return pd.to_datetime(value, format="%d-%b-%Y").date()
    except (ValueError, TypeError):
        return None


def kotak_expiry_epoch(value):
    """
    Convert Kotak's expiry timestamps, which count seconds from 1980-01-01 rather than the 1970 Unix epoch.

    Args:
        value (str | float | None): Raw seconds value from the Kotak table, or None.

    Returns:
        datetime.date | None: The expiry date, or None when the input is None or empty.
    """
    if value is None or pd.isna(value):
        return None
    return pd.to_datetime(float(value), unit="s", origin="1980-01-01").date()


def strip_exchange_prefix(value):
    """
    Remove an ``EXCHANGE:`` prefix from a broker's own ticker column, for example Fyers' ``symbol_ticker`` of ``BSE:AXISBANK26SEPFUT``.

    Args:
        value (str | float | None): Raw ticker value, or None.

    Returns:
        str | None: The ticker after the last colon, or None when the input is None or empty.
    """
    if value is None or pd.isna(value):
        return None
    return str(value).split(":")[-1]


TRANSFORMS = {
    "divide_by_100": divide_by_100,
    "divide_by_10_thousand": divide_by_10_thousand,
    "divide_by_10_million": divide_by_10_million,
    "day_month_year_date": day_month_year_date,
    "day_month_name_year_date": day_month_name_year_date,
    "unix_epoch_date": unix_epoch_date,
    "kotak_expiry_epoch": kotak_expiry_epoch,
    "strip_exchange_prefix": strip_exchange_prefix,
}


def canonical_identity_value(value):
    """
    Stringify one identity field for hashing, the same way regardless of the numeric type the caller happens to pass.

    ``str(Decimal('340'))`` is ``'340'`` but ``str(float('340'))`` is ``'340.0'`` — two different hash inputs for the same real strike price depending on whether the value arrived from Postgres or from a float cast. Every numeric value is therefore routed through Decimal first, so the same real-world value always hashes the same way.

    Args:
        value (str | float | None): One identity field value of any type.

    Returns:
        str: The canonical string form used as hash input.
    """
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        decimal_value = Decimal(str(value))
        return format(decimal_value.normalize(), "f")
    if isinstance(value, (int, Decimal)):
        return format(Decimal(value).normalize(), "f")
    return str(value)


def instrument_id(exchange, segment, shape, identity):
    """
    Compute the deterministic instrument id as a UUID5 over the natural key.

    Two different brokers carrying the same real-world instrument compute the same id independently, which is the entire merge mechanism: upserts converge on one ``unified.instruments`` row with no lookup or registry step.

    Args:
        exchange (str): Canonical lowercase exchange name, for example "nse".
        segment (str): Exchange-prefixed segment value, for example "nse_equities".
        shape (str): One of "security", "future", or "option".
        identity (dict): The identity fields for the shape, for example {"symbol": "RELIANCE"}.

    Returns:
        str: The UUID5 instrument id.
    """
    parts = [
        exchange,
        segment,
        shape,
    ]
    for field_name in sorted(identity):
        parts.append(canonical_identity_value(identity[field_name]))
    return str(uuid.uuid5(IDENTITY_NAMESPACE, "|".join(parts)))


class BrokerMappingAdapter:
    """Base class for per-broker mapping adapters, holding the rules engine, the identity computation, and the database writes shared by all ten brokers."""

    BROKER_NAME = ""

    def __init__(self):
        """
        Load and validate the broker's rules file and create the database engine.

        Raises:
            NotImplementedError: If the subclass did not set BROKER_NAME.
            ValueError: If the rules file fails validation.
            FileNotFoundError: If the broker has no rules file.
        """
        if not self.BROKER_NAME:
            raise NotImplementedError(f"{type(self).__name__} must set BROKER_NAME")
        with open(RULES_DIRECTORY / f"{self.BROKER_NAME}.yaml") as rules_file:
            self.config = yaml.safe_load(rules_file)
        self._validate_config()
        self.engine = get_postgres_engine()

    def _validate_config(self):
        """
        Check the loaded rules file against the canonical vocabulary.

        Every configured segment must be a real canonical segment for its exchange with the matching shape, and the segments must appear in the canonical asset-class order. The file must end with the unprefixed ``uncategorised`` entry on exchange ``unknown``, which is the guaranteed fallback for rows whose exchange cannot be determined; ``unknown`` is allowed for that one entry only, since it is the value stored in the exchange column of the mapped table for those rows.

        Raises:
            ValueError: On any invalid exchange, segment, shape, ordering, or missing or misplaced uncategorised entry.
        """
        previous_rank = None
        has_plain_uncategorised = False
        for segment_configuration in self.config["segments"]:
            exchange = segment_configuration["exchange"]
            segment = segment_configuration["segment"]
            shape = segment_configuration["shape"]
            is_plain_uncategorised = segment == "uncategorised" and exchange == "unknown"
            if is_plain_uncategorised:
                has_plain_uncategorised = True
                previous_rank = (1000000000, 1000000000)
                continue
            if exchange not in CANONICAL_EXCHANGES:
                raise ValueError(
                    f"{self.BROKER_NAME}: {exchange!r} is not a canonical exchange, "
                    f"expected one of {CANONICAL_EXCHANGES} or 'unknown' on the plain "
                    f"'uncategorised' entry"
                )
            bare_segment = segment
            if segment.startswith(f"{exchange}_"):
                bare_segment = segment[len(exchange) + 1:]
            try:
                declared_shape = segment_shape(bare_segment)
            except ValueError:
                raise ValueError(
                    f"{self.BROKER_NAME}: {segment!r} is not a canonical segment for exchange "
                    f"{exchange!r}; use the canonical segment value instead"
                )
            if declared_shape != shape:
                raise ValueError(
                    f"{self.BROKER_NAME}: segment {segment!r} has shape {declared_shape!r} "
                    f"in the canonical vocabulary, not {shape!r} as configured here"
                )
            rank = segment_rank(exchange, bare_segment)
            if previous_rank is not None and rank < previous_rank:
                raise ValueError(
                    f"{self.BROKER_NAME}: segment {segment!r} appears out of canonical order; "
                    f"segments must be listed fixed income, equities, currencies, commodities, "
                    f"then the catch-alls, then the uncategorised buckets, and within a class "
                    f"simple instruments, futures, options, indices, index futures, index options"
                )
            previous_rank = rank
        if not has_plain_uncategorised:
            raise ValueError(
                f"{self.BROKER_NAME}: the rules file must end with the unprefixed "
                f"'uncategorised' entry on exchange 'unknown'"
            )

    def segment_config(self, segment):
        """
        Look up one segment configuration by its segment value.

        Args:
            segment (str): The exchange-prefixed segment value, for example "nse_equities".

        Returns:
            dict | None: The matching segment configuration, or None when the rules file does not configure that segment.
        """
        for segment_configuration in self.config["segments"]:
            if segment_configuration["segment"] == segment:
                return segment_configuration
        return None

    def _field(self, raw_row, specification):
        """
        Read one raw column value, applying a named transform when the specification asks for one.

        Args:
            raw_row (dict): One raw row from the broker's instrument table.
            specification: Either a bare column name, or a dict with "column" and optionally "transform" keys.

        Returns:
            The column value, transformed if requested.
        """
        if isinstance(specification, dict):
            value = raw_row.get(specification["column"])
            transform = specification.get("transform")
            if transform:
                return TRANSFORMS[transform](value)
            return value
        return raw_row.get(specification)

    def _row_matches(self, raw_row, match):
        """
        Check one equality rule against a raw row.

        Args:
            raw_row (dict): One raw row from the broker's instrument table.
            match (dict): Mapping of raw column name to expected value, or to a list of acceptable values.

        Returns:
            bool: True when every column in the rule matches.
        """
        for column_name, expected in match.items():
            actual = raw_row.get(column_name)
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False
        return True

    def classify(self, raw_row):
        """
        Find the first segment whose rules match the raw row.

        Subclasses override this when the broker's classification cannot be expressed as equality rules — Zerodha is the fully custom case — and call this base implementation only for the segments their rules do cover.

        Args:
            raw_row (dict): One raw row from the broker's instrument table.

        Returns:
            dict | None: The matched segment configuration, or None when no segment matches.
        """
        for segment_configuration in self.config["segments"]:
            for rule in segment_configuration["rules"]:
                if self._row_matches(raw_row, rule["match"]):
                    return segment_configuration
        return None

    def classify_extra(self, raw_row):
        """
        Return additional segments this raw row also belongs to beyond the primary match.

        A raw row can genuinely satisfy more than one segment's criteria at once — a BSE row can be both a real equity and a crossref-confirmed exchange traded fund. The base implementation returns an empty list; the brokers where dual membership was confirmed override it.

        Args:
            raw_row (dict): One raw row from the broker's instrument table.

        Returns:
            list[dict]: Additional segment configurations, empty by default.
        """
        return []

    def to_identity(self, raw_row, segment_configuration):
        """
        Build the unified identity fields for a raw row under one segment.

        Args:
            raw_row (dict): One raw row from the broker's instrument table.
            segment_configuration (dict): The segment configuration whose identity mapping applies.

        Returns:
            dict: Identity fields, with "symbol" for securities and "underlying_symbol", "expiry_date", "strike_price", "option_type" for derivatives.

        Raises:
            ValueError: If an expiry value is numeric with no explicit transform, since the epoch unit cannot be guessed safely.
        """
        identity = {}
        for field_name, specification in segment_configuration["identity"].items():
            value = self._field(raw_row, specification)
            if field_name == "expiry_date" and value is not None and not isinstance(value, date_class):
                if isinstance(value, (int, float)) and not isinstance(specification, dict):
                    raise ValueError(
                        f"expiry_date for specification {specification!r} is numeric "
                        f"({value!r}) with no transform; add an explicit "
                        f"{{column, transform}} specification rather than relying on "
                        f"the generic date fallback"
                    )
                value = pd.to_datetime(value).date()
            if field_name in ("symbol", "underlying_symbol") and value is not None:
                value = str(value).strip()
            if field_name == "strike_price" and value is not None:
                value = float(value)
            identity[field_name] = value
        return identity

    def to_broker_fields(self, raw_row, segment_configuration):
        """
        Build the per-broker mapping fields for a raw row under one segment.

        A tick size of zero or below is stored as None, because no instrument moves in steps of nothing, and brokers send 0 or -1 where they have no tick for a row.

        Args:
            raw_row (dict): One raw row from the broker's instrument table.
            segment_configuration (dict): The segment configuration whose broker field mapping applies.

        Returns:
            dict: Keys "broker_token" (str), "broker_symbol", "order_symbol", "lot_size" (float | None), and "tick_size" (float | None).
        """
        broker_field_specifications = segment_configuration["broker_fields"]
        lot_size = self._field(raw_row, broker_field_specifications["lot_size"])
        tick_size = self._field(raw_row, broker_field_specifications["tick_size"])
        if tick_size is None or pd.isna(tick_size) or float(tick_size) <= 0:
            tick_size = None
        else:
            tick_size = float(tick_size)
        order_symbol_specification = broker_field_specifications.get("order_symbol")
        if order_symbol_specification is None:
            order_symbol = None
        else:
            order_symbol = self._field(raw_row, order_symbol_specification)
        if order_symbol is not None and pd.isna(order_symbol):
            order_symbol = None
        return {
            "broker_token": str(self._field(raw_row, broker_field_specifications["token"])),
            "broker_symbol": self._field(raw_row, broker_field_specifications["broker_symbol"]),
            "order_symbol": None if order_symbol is None else str(order_symbol).strip(),
            "lot_size": None if lot_size is None or pd.isna(lot_size) else float(lot_size),
            "tick_size": tick_size,
        }

    def uncategorised_exchange(self, raw_row):
        """
        Determine the canonical exchange for a row that matched no segment, so it can be filed into the right per-exchange uncategorised bucket.

        The base implementation returns None, which routes the row to the unprefixed ``uncategorised`` segment. Brokers whose raw rows carry a usable exchange column override this.

        Args:
            raw_row (dict): One raw row from the broker's instrument table.

        Returns:
            str | None: Canonical lowercase exchange name, or None.
        """
        return None

    def _uncategorised_config(self, raw_row):
        """
        Pick the uncategorised segment configuration a row falls back into.

        The per-exchange bucket is used when ``uncategorised_exchange`` resolves an exchange and the rules file configures that bucket; otherwise the unprefixed ``uncategorised`` entry is used.

        Args:
            raw_row (dict): One raw row from the broker's instrument table.

        Returns:
            dict: The uncategorised segment configuration.

        Raises:
            ValueError: If no uncategorised configuration exists, which validation should have made impossible.
        """
        exchange = self.uncategorised_exchange(raw_row)
        if exchange is not None:
            preferred = self.segment_config(segment_value(exchange, "uncategorised"))
            if preferred is not None:
                return preferred
        fallback = self.segment_config("uncategorised")
        if fallback is None:
            raise ValueError(
                f"{self.BROKER_NAME}: no uncategorised segment configuration found, "
                f"which validation should have made impossible"
            )
        return fallback

    def read_raw_rows(self, connection, mapping_date):
        """
        Read the broker's raw rows for one date.

        Adapters override this where the fetch itself is part of the mapping: to impose a row order the classification depends on, or to bring in rows the plain query would miss.

        Args:
            connection (sqlalchemy.engine.Connection): An open SQLAlchemy connection.
            mapping_date (datetime.date): The raw snapshot date to read.

        Returns:
            pandas.DataFrame: The raw rows for that date.
        """
        raw_table = self.config["raw_table"]
        return pd.read_sql(
            text(f"SELECT * FROM {raw_table} WHERE download_date = :d"),
            connection,
            params={
                "d": mapping_date,
            },
        )

    def run(self, mapping_date):
        """
        Classify every raw row for one date and write the mapped tables.

        The run is self-correcting: this broker's rows for the mapping date are deleted before the insert, so a re-run after a fix leaves no stale rows from an earlier buggy run.

        Args:
            mapping_date (datetime.date): The raw snapshot date to map.

        Returns:
            dict: Summary with keys "broker", "mapping_date", "raw_rows", "matched", "uncategorised", "memberships", "instruments_upserted", and "errors". "matched" and "uncategorised" count raw rows and together equal "raw_rows"; "memberships" counts the rows written, which is higher wherever a row belongs to more than one segment. "errors" is a list of (segment, message) pairs.
        """
        with self.engine.connect() as connection:
            raw = self.read_raw_rows(connection, mapping_date)

        instrument_rows = {}
        broker_rows = {}
        errors = []
        matched = 0
        uncategorised = 0
        memberships = 0

        for raw_row in raw.to_dict("records"):
            segment_configuration = self.classify(raw_row)
            if segment_configuration is None:
                segment_configurations = [self._uncategorised_config(raw_row)]
                was_uncategorised = True
                uncategorised += 1
            else:
                segment_configurations = [segment_configuration] + self.classify_extra(raw_row)
                was_uncategorised = False
                matched += 1
            for one_segment_configuration in segment_configurations:
                try:
                    identity = self.to_identity(raw_row, one_segment_configuration)
                    broker_fields = self.to_broker_fields(raw_row, one_segment_configuration)
                except Exception as exception:
                    errors.append((one_segment_configuration["segment"], str(exception)))
                    continue
                if was_uncategorised:
                    symbol = identity.get("symbol")
                    if symbol is None or str(symbol).strip() == "":
                        identity["symbol"] = broker_fields["broker_token"]
                memberships += 1

                exchange = one_segment_configuration["exchange"]
                segment = one_segment_configuration["segment"]
                shape = one_segment_configuration["shape"]
                computed_id = instrument_id(exchange, segment, shape, identity)
                instrument_rows[computed_id] = {
                    "instrument_id": computed_id,
                    "exchange": exchange,
                    "segment": segment,
                    "shape": shape,
                    "symbol": identity.get("symbol"),
                    "underlying_symbol": identity.get("underlying_symbol"),
                    "expiry_date": identity.get("expiry_date"),
                    "strike_price": identity.get("strike_price"),
                    "option_type": identity.get("option_type"),
                    "first_seen_date": mapping_date,
                    "last_seen_date": mapping_date,
                }
                broker_rows[computed_id] = {
                    "instrument_id": computed_id,
                    "broker": self.BROKER_NAME,
                    "mapping_date": mapping_date,
                    "broker_token": broker_fields["broker_token"],
                    "broker_symbol": broker_fields["broker_symbol"],
                    "order_symbol": broker_fields["order_symbol"],
                    "lot_size": broker_fields["lot_size"],
                    "tick_size": broker_fields["tick_size"],
                }

        self._write_results(instrument_rows, broker_rows, mapping_date)

        summary = {
            "broker": self.BROKER_NAME,
            "mapping_date": mapping_date,
            "raw_rows": len(raw),
            "matched": matched,
            "uncategorised": uncategorised,
            "memberships": memberships,
            "instruments_upserted": len(instrument_rows),
            "errors": errors,
        }
        print(
            f"{self.BROKER_NAME}: {matched}/{len(raw)} raw row(s) classified, "
            f"{uncategorised} uncategorised, {memberships} segment membership(s), "
            f"{len(instrument_rows)} distinct instrument(s), {len(errors)} error(s)."
        )
        return summary

    def _write_results(self, instrument_rows, broker_rows, mapping_date):
        """
        Write one run's rows into the mapped tables inside a single transaction.

        Both row lists are sorted by instrument id before the insert so concurrent writers acquire locks in the same order, which is the standard fix for the multi-writer deadlock this design was observed hitting when adapters ran in parallel.

        The seen dates widen rather than overwrite, so they do not depend on the order dates happen to be mapped in. Assigning the run's date to the last seen date directly looks equivalent while a backfill walks forward, and is wrong the moment any older date is mapped afterwards: it drags the last seen date backwards, and leaves the first seen date frozen at whichever date was written first rather than the earliest the instrument was actually seen.

        Args:
            instrument_rows (dict): Mapping of instrument id to the unified.instruments row.
            broker_rows (dict): Mapping of instrument id to the unified.broker_mappings row.
            mapping_date (datetime.date): The mapping date the run covers.
        """
        sorted_instruments = sorted(instrument_rows.values(), key=lambda row: row["instrument_id"])
        sorted_brokers = sorted(broker_rows.values(), key=lambda row: row["instrument_id"])

        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"DELETE FROM {tables.BROKER_MAPPINGS} "
                    "WHERE broker = :b AND mapping_date = :d"
                ),
                {
                    "b": self.BROKER_NAME,
                    "d": mapping_date,
                },
            )
            if sorted_instruments:
                connection.execute(
                    text(
                        f"""
                        INSERT INTO {tables.MASTER} AS master
                            (instrument_id, exchange, segment, shape, symbol, underlying_symbol,
                             expiry_date, strike_price, option_type, first_seen_date, last_seen_date)
                        VALUES
                            (:instrument_id, :exchange, :segment, :shape, :symbol, :underlying_symbol,
                             :expiry_date, :strike_price, :option_type, :first_seen_date, :last_seen_date)
                        ON CONFLICT (instrument_id) DO UPDATE SET
                            first_seen_date = LEAST(master.first_seen_date, EXCLUDED.first_seen_date),
                            last_seen_date = GREATEST(master.last_seen_date, EXCLUDED.last_seen_date)
                        """
                    ),
                    sorted_instruments,
                )
            if sorted_brokers:
                connection.execute(
                    text(
                        f"""
                        INSERT INTO {tables.BROKER_MAPPINGS}
                            (instrument_id, broker, broker_token, broker_symbol, order_symbol, lot_size, tick_size, mapping_date)
                        VALUES
                            (:instrument_id, :broker, :broker_token, :broker_symbol, :order_symbol, :lot_size, :tick_size, :mapping_date)
                        ON CONFLICT (instrument_id, broker, mapping_date) DO UPDATE SET
                            broker_token = EXCLUDED.broker_token, broker_symbol = EXCLUDED.broker_symbol,
                            order_symbol = EXCLUDED.order_symbol,
                            lot_size = EXCLUDED.lot_size, tick_size = EXCLUDED.tick_size
                        """
                    ),
                    sorted_brokers,
                )