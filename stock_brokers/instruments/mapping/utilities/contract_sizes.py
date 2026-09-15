"""
Decide, once per mapping date, how many quotation units one lot of every currency and commodity derivative is.

    python -m stock_brokers.instruments.mapping.utilities.contract_sizes
    python -m stock_brokers.instruments.mapping.utilities.contract_sizes --date 2026-09-15

The brokers' own `lot_size` figures cannot be compared on these markets, because each broker counts a lot in its own unit: on MCX, GOLD's lot is 1 at Zerodha (one lot), 1 at Kotak (one kilogram) and 100 at Groww (quotation units of 10 grams). Several brokers' instrument files also carry the exchange's contract size fields, and those are read here as independent sources, each in quotation units: Wisdom Capital's `multiplier`, Kotak's lot size times its general numerator over its general denominator (or its multiplier on the currency segment), Groww's commodity lot size, Shoonya's lot size times its multiplier on NSE currencies, and Stoxkart's lot size on the currency and NCDEX segments.

A contract is `confirmed` when at least two sources give a size and every one gives the same size. It is `single_source` when exactly one does, `conflict` when sources disagree, and `no_source` when none does. `tradeable` is true for a confirmed contract, and for a single-source contract only on BSE currencies and NCDEX, where Stoxkart is the only broker that lists them. The decision and every source's figure are written to `unified.contract_sizes` for the date, so an order reads a stored decision rather than making one.
"""

import argparse
import collections
import datetime
import decimal
import json

from sqlalchemy import text

from stock_brokers.instruments.mapping.utilities import tables
from stock_brokers.instruments.mapping.utilities.segments import CANONICAL_EXCHANGES
from stock_brokers.instruments.mapping.utilities.segments import CANONICAL_SEGMENTS
from utilities.configurations import get_postgres_engine


class ContractSizeSource:
    """
    One broker instrument file field, or combination of fields, that states a contract's size in quotation units.

    A subclass sets the class attributes and `units_expression`. The source is read by joining the date's broker mappings to that broker's raw snapshot on the broker token, restricted to the raw exchange labels the source is trusted on, because a token is not unique across a broker's exchanges.

    Attributes:
        NAME (str): The source's name, as it is recorded in `unified.contract_sizes.sources`.
        BROKER (str): The broker whose snapshot is read.
        TOKEN_COLUMN (str): The snapshot column holding the broker token.
        EXCHANGE_COLUMN (str): The snapshot column holding the exchange label.
        EXCHANGES (list): The exchange labels the source is read on.
    """

    NAME = None
    BROKER = None
    TOKEN_COLUMN = None
    EXCHANGE_COLUMN = None
    EXCHANGES = []

    def numeric(self, column):
        """
        An SQL expression reading a snapshot column as a number, or null when it does not hold one.

        Args:
            column (str): The snapshot column.

        Returns:
            str: The SQL expression.
        """
        return (
            f"(CASE WHEN raw.\"{column}\"::text ~ '^-?[0-9]+(\\.[0-9]+)?$' "
            f"THEN raw.\"{column}\"::text::numeric END)"
        )

    def units_expression(self):
        """
        The SQL expression giving the contract's size in quotation units.

        Returns:
            str: The SQL expression.

        Raises:
            NotImplementedError: Always, in the base class.
        """
        raise NotImplementedError

    def statement(self):
        """
        The query reading this source for every live contract in the given segments on a date.

        Returns:
            sqlalchemy.sql.elements.TextClause: The query, taking `mapping_date`, `segments` and `exchanges`.
        """
        return text(
            f"SELECT m.instrument_id::text AS instrument_id, {self.units_expression()} AS units "
            f"FROM {tables.BROKER_MAPPINGS} m "
            f"JOIN {tables.MASTER} i ON i.instrument_id = m.instrument_id "
            f"JOIN {self.BROKER}.instruments raw "
            f"ON raw.\"{self.TOKEN_COLUMN}\"::text = m.broker_token "
            "AND raw.download_date = m.mapping_date "
            "WHERE m.broker = :broker "
            "AND m.mapping_date = :mapping_date "
            "AND i.segment = ANY(:segments) "
            "AND (i.expiry_date IS NULL OR i.expiry_date >= :mapping_date) "
            f"AND raw.\"{self.EXCHANGE_COLUMN}\"::text = ANY(:exchanges)"
        )

    def read(self, connection, mapping_date, segments):
        """
        Reads this source's size for every live contract it lists.

        Args:
            connection (sqlalchemy.engine.Connection): An open connection.
            mapping_date (datetime.date): The mapping date.
            segments (list): The exchange-prefixed segments to read.

        Returns:
            dict: Instrument ids to sizes as decimals, leaving out rows whose size is missing, zero or negative.
        """
        rows = connection.execute(
            self.statement(),
            {
                "broker": self.BROKER,
                "mapping_date": mapping_date,
                "segments": segments,
                "exchanges": self.EXCHANGES,
            },
        )
        sizes = {}
        for row in rows:
            if row.units is None:
                continue
            units = decimal.Decimal(row.units)
            if units <= 0:
                continue
            sizes[row.instrument_id] = units.normalize()
        return sizes


class WisdomCapitalMultiplierSource(ContractSizeSource):
    """Wisdom Capital's XTS `multiplier`, which is the contract size in quotation units on MCX and NSE commodities."""

    NAME = "wisdom_capital_multiplier"
    BROKER = "wisdom_capital"
    TOKEN_COLUMN = "exchangeinstrumentid"
    EXCHANGE_COLUMN = "exchangesegment"
    EXCHANGES = [
        "MCXFO",
        "NSECO",
    ]

    def units_expression(self):
        """
        The `multiplier` column.

        Returns:
            str: The SQL expression.
        """
        return self.numeric("multiplier")


class KotakContractSizeSource(ContractSizeSource):
    """Kotak's lot size in its trading unit, converted to quotation units with its general numerator and denominator, and scaled by its multiplier where it gives one, as on currencies."""

    NAME = "kotak_contract_size"
    BROKER = "kotak"
    TOKEN_COLUMN = "psymbol"
    EXCHANGE_COLUMN = "pexchseg"
    EXCHANGES = [
        "mcx_fo",
        "nse_com",
        "cde_fo",
    ]

    def units_expression(self):
        """
        `llotsize` times `lmultiplier` when it is positive, times `dgennum`, over `dgenden`.

        Returns:
            str: The SQL expression.
        """
        lot_size = self.numeric("llotsize")
        multiplier = self.numeric("lmultiplier")
        numerator = self.numeric("dgennum")
        denominator = self.numeric("dgenden")
        return (
            f"({lot_size} "
            f"* (CASE WHEN {multiplier} > 0 THEN {multiplier} ELSE 1 END) "
            f"* {numerator} / NULLIF({denominator}, 0))"
        )


class GrowwLotSizeSource(ContractSizeSource):
    """Groww's lot size on its commodity segment, which Groww gives in quotation units."""

    NAME = "groww_lot_size"
    BROKER = "groww"
    TOKEN_COLUMN = "exchange_token"
    EXCHANGE_COLUMN = "segment"
    EXCHANGES = [
        "COMMODITY",
    ]

    def units_expression(self):
        """
        The `lot_size` column.

        Returns:
            str: The SQL expression.
        """
        return self.numeric("lot_size")


class ShoonyaCurrencySource(ContractSizeSource):
    """Shoonya's lot size times its multiplier on NSE currencies, where it gives a lot size of 1 and a multiplier of the contract size."""

    NAME = "shoonya_lot_size_times_multiplier"
    BROKER = "shoonya"
    TOKEN_COLUMN = "token"
    EXCHANGE_COLUMN = "exchange"
    EXCHANGES = [
        "CDS",
    ]

    def units_expression(self):
        """
        `lotsize` times `multiplier`.

        Returns:
            str: The SQL expression.
        """
        return f"({self.numeric('lotsize')} * {self.numeric('multiplier')})"


class StoxkartLotSizeSource(ContractSizeSource):
    """Stoxkart's lot size on the NSE and BSE currency segments and NCDEX."""

    NAME = "stoxkart_lot_size"
    BROKER = "stoxkart"
    TOKEN_COLUMN = "token"
    EXCHANGE_COLUMN = "exchange"
    EXCHANGES = [
        "NSECD",
        "BSECD",
        "NCDEX",
    ]

    def units_expression(self):
        """
        The `lot_size` column.

        Returns:
            str: The SQL expression.
        """
        return self.numeric("lot_size")


class ContractSizeDecision:
    """
    The rule that turns the sources' figures for one contract into a stored decision.

    Attributes:
        SINGLE_SOURCE_MARKETS (list): The `(exchange, asset class)` markets where one source is enough to trade, because only one broker lists them.
    """

    SINGLE_SOURCE_MARKETS = [
        (
            "bse",
            "currency",
        ),
        (
            "ncdex",
            "commodity",
        ),
    ]

    def market(self, segment):
        """
        The exchange and asset class of an exchange-prefixed segment.

        Args:
            segment (str): The segment, such as `mcx_commodity_futures`.

        Returns:
            tuple: `(exchange, asset class)`, where the asset class is `currency` or `commodity`.
        """
        exchange, _, bare_segment = segment.partition("_")
        if bare_segment.startswith("currency"):
            return (exchange, "currency")
        return (exchange, "commodity")

    def decide(self, segment, figures):
        """
        Decides one contract's size from what each source says.

        Args:
            segment (str): The contract's exchange-prefixed segment.
            figures (dict): Source names to sizes as decimals, for the sources that give one.

        Returns:
            tuple: `(units_per_lot, status, tradeable)`, where `units_per_lot` is a decimal or None, `status` one of `confirmed`, `single_source`, `conflict` and `no_source`, and `tradeable` a bool.
        """
        distinct_sizes = set(figures.values())
        if not figures:
            return None, "no_source", False
        if len(distinct_sizes) > 1:
            return None, "conflict", False
        units_per_lot = next(iter(distinct_sizes))
        if len(figures) == 1:
            tradeable = self.market(segment) in self.SINGLE_SOURCE_MARKETS
            return units_per_lot, "single_source", tradeable
        return units_per_lot, "confirmed", True


class ContractSizeResolver:
    """
    Reads every source for a mapping date, decides each contract's size and writes the decisions.

    Attributes:
        WRITE_BATCH_ROWS (int): How many rows are inserted per statement.
        SOURCES (list): The source classes read, in the order their figures are recorded.
        engine (sqlalchemy.engine.Engine): The engine over TimescaleDB.
        decision (ContractSizeDecision): The rule applied to each contract.
    """

    WRITE_BATCH_ROWS = 10000
    SOURCES = [
        WisdomCapitalMultiplierSource,
        KotakContractSizeSource,
        GrowwLotSizeSource,
        ShoonyaCurrencySource,
        StoxkartLotSizeSource,
    ]

    def __init__(self, engine=None):
        """
        Builds the resolver.

        Args:
            engine (sqlalchemy.engine.Engine | None): The engine to use. None builds one from the environment.

        Returns:
            None: This method returns nothing.
        """
        self.engine = engine or get_postgres_engine()
        self.decision = ContractSizeDecision()

    def segments(self):
        """
        Every exchange-prefixed currency and commodity futures and options segment.

        Returns:
            list: The segments.
        """
        segments = []
        for bare_segment, shape in CANONICAL_SEGMENTS:
            if shape not in ("future", "option"):
                continue
            if not bare_segment.startswith(("currency", "commodity")):
                continue
            for exchange in CANONICAL_EXCHANGES:
                segments.append(f"{exchange}_{bare_segment}")
        return segments

    def live_contracts(self, connection, mapping_date, segments):
        """
        Every contract mapped on the date in the segments that has not expired.

        Args:
            connection (sqlalchemy.engine.Connection): An open connection.
            mapping_date (datetime.date): The mapping date.
            segments (list): The exchange-prefixed segments.

        Returns:
            dict: Instrument ids to their segments.
        """
        statement = text(
            f"SELECT DISTINCT m.instrument_id::text AS instrument_id, i.segment "
            f"FROM {tables.BROKER_MAPPINGS} m "
            f"JOIN {tables.MASTER} i ON i.instrument_id = m.instrument_id "
            "WHERE m.mapping_date = :mapping_date "
            "AND i.segment = ANY(:segments) "
            "AND (i.expiry_date IS NULL OR i.expiry_date >= :mapping_date)"
        )
        contracts = {}
        rows = connection.execute(
            statement,
            {
                "mapping_date": mapping_date,
                "segments": segments,
            },
        )
        for row in rows:
            contracts[row.instrument_id] = row.segment
        return contracts

    def decisions(self, mapping_date):
        """
        Decides every live contract's size for the date.

        Args:
            mapping_date (datetime.date): The mapping date.

        Returns:
            list: One dictionary per contract with `instrument_id`, `mapping_date`, `segment`, `units_per_lot`, `status`, `tradeable` and `sources`.
        """
        segments = self.segments()
        figures_by_contract = collections.defaultdict(dict)
        with self.engine.connect() as connection:
            contracts = self.live_contracts(connection, mapping_date, segments)
            for source_class in self.SOURCES:
                source = source_class()
                sizes = source.read(connection, mapping_date, segments)
                for instrument_id, units in sizes.items():
                    figures_by_contract[instrument_id][source.NAME] = units
        rows = []
        for instrument_id, segment in contracts.items():
            figures = figures_by_contract.get(instrument_id, {})
            units_per_lot, status, tradeable = self.decision.decide(
                segment,
                figures,
            )
            recorded_figures = {}
            for source_name, units in figures.items():
                recorded_figures[source_name] = format(units, "f")
            rows.append({
                "instrument_id": instrument_id,
                "mapping_date": mapping_date,
                "segment": segment,
                "units_per_lot": units_per_lot,
                "status": status,
                "tradeable": tradeable,
                "sources": json.dumps(recorded_figures, sort_keys=True),
            })
        return rows

    def write(self, mapping_date, rows):
        """
        Replaces the date's decisions with the given rows, in one transaction.

        Args:
            mapping_date (datetime.date): The mapping date.
            rows (list): The decisions, as `decisions` returns them.

        Returns:
            int: The number of rows written.
        """
        delete_statement = text(
            f"DELETE FROM {tables.CONTRACT_SIZES} "
            "WHERE mapping_date = :mapping_date"
        )
        insert_statement = text(
            f"INSERT INTO {tables.CONTRACT_SIZES} "
            "(instrument_id, mapping_date, segment, units_per_lot, status, tradeable, sources) "
            "VALUES (CAST(:instrument_id AS uuid), :mapping_date, :segment, :units_per_lot, :status, :tradeable, "
            "CAST(:sources AS jsonb))"
        )
        with self.engine.begin() as connection:
            connection.execute(
                delete_statement,
                {
                    "mapping_date": mapping_date,
                },
            )
            for start in range(0, len(rows), self.WRITE_BATCH_ROWS):
                batch = rows[start:start + self.WRITE_BATCH_ROWS]
                connection.execute(insert_statement, batch)
        return len(rows)

    def run(self, mapping_date):
        """
        Decides and writes every live contract's size for the date.

        Args:
            mapping_date (datetime.date): The mapping date.

        Returns:
            collections.Counter: `(segment, status, tradeable)` to the number of contracts.
        """
        rows = self.decisions(mapping_date)
        self.write(mapping_date, rows)
        summary = collections.Counter()
        for row in rows:
            summary[(row["segment"], row["status"], row["tradeable"])] += 1
        return summary


class ContractSizeCommand:
    """The command line: decide a date's contract sizes and print how many contracts each segment has in each status."""

    def run(self):
        """
        Parses the arguments, runs the resolver and prints the summary.

        Returns:
            int: The exit code: 0 on success, 2 for a malformed date.
        """
        parser = argparse.ArgumentParser(
            description="Decide the contract size of every live currency and commodity derivative for a mapping date.",
        )
        parser.add_argument(
            "--date",
            help="the mapping date, as YYYY-MM-DD. Today when omitted.",
        )
        arguments = parser.parse_args()
        mapping_date = datetime.date.today()
        if arguments.date:
            try:
                mapping_date = datetime.date.fromisoformat(arguments.date)
            except ValueError:
                print(f"--date needs a date as YYYY-MM-DD, not {arguments.date!r}.")
                return 2
        summary = ContractSizeResolver().run(mapping_date)
        print(f"contract sizes for {mapping_date}")
        print(f"  {'segment':<32} {'status':<14} {'tradeable':<10} {'contracts':>9}")
        for segment, status, tradeable in sorted(summary):
            count = summary[(segment, status, tradeable)]
            print(f"  {segment:<32} {status:<14} {str(tradeable):<10} {count:>9}")
        return 0


if __name__ == "__main__":
    raise SystemExit(ContractSizeCommand().run())
