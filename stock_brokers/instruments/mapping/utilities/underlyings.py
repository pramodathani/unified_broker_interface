"""
Decide, once per mapping date, which instrument every live future and option is written on, from the brokers' own records.

    python -m stock_brokers.instruments.mapping.utilities.underlyings
    python -m stock_brokers.instruments.mapping.utilities.underlyings --date 2026-09-28
    python -m stock_brokers.instruments.mapping.utilities.underlyings --date 2026-09-28 --dry-run

A derivative names its underlying only by `underlying_symbol`, and that name does not always match the underlying's own symbol: the nse's `NIFTYFPI` contracts are written on the index stored as "Nifty FPI 150", and the bse's `SENSEX50` contracts on the one stored as "SNSX50". Three brokers' instrument files say which instrument each derivative is written on, by the exchange's own code for it, and `raw_attributes.py` keeps that code as the `underlying_token` attribute: Dhan's `underlying_security_id`, Groww's `underlying_exchange_token` and Fyers' `underlying_scrip_code`. Wisdom Capital's `underlyinginstrumentid` is left out, because it is prefixed with a segment code and is -1 for every index.

The same exchange codes identify the candidates. Dhan's and Groww's broker token is the exchange's code for a share or a future, and Fyers keeps an index's and a share's own exchange code as their `underlying_token`, which covers the indices, whose Dhan and Groww tokens are not the exchange's code. A code is looked up only among the candidates on the derivative's exchange and in the segments its underlying can be in: the family's cash or index segment, and for an option also the family's futures segment, because an MCX option is written on a future. That restriction matters, because the same code names unrelated instruments in other segments: an nse commodity future's code also names an equity index.

A contract is `resolved` when every code any broker gives leads to one and the same instrument, and that instrument is its `underlying_instrument_id`. It is `ambiguous` when the codes lead to more than one, `unresolved` when they lead to none, and `no_code` when no broker gives a code. The decision and every broker's code are written to `unified.underlyings` for the date, and `warm_cache.py` copies the resolved ones into Redis for the REST API's `/details` and `/master`.
"""

import argparse
import collections
import datetime
import json

from sqlalchemy import text

from stock_brokers.instruments.mapping.utilities import tables
from utilities.configurations import get_postgres_engine

CODE_BROKERS = [
    "dhan",
    "groww",
    "fyers",
]

TOKEN_CODE_BROKERS = [
    "dhan",
    "groww",
]

ATTRIBUTE_CODE_BROKERS = [
    "fyers",
]

CANDIDATE_SEGMENTS = {
    "equity_futures": [
        "equities",
    ],
    "equity_options": [
        "equities",
        "equity_futures",
    ],
    "equity_index_futures": [
        "equity_indices",
    ],
    "equity_index_options": [
        "equity_indices",
        "equity_index_futures",
    ],
    "fixed_income_futures": [
        "fixed_income",
    ],
    "fixed_income_options": [
        "fixed_income",
        "fixed_income_futures",
    ],
    "fixed_income_index_futures": [
        "fixed_income_indices",
    ],
    "fixed_income_index_options": [
        "fixed_income_indices",
        "fixed_income_index_futures",
    ],
    "commodity_futures": [
        "commodities",
    ],
    "commodity_options": [
        "commodities",
        "commodity_futures",
    ],
    "commodity_index_futures": [
        "commodity_indices",
    ],
    "commodity_index_options": [
        "commodity_indices",
        "commodity_index_futures",
    ],
    "currency_futures": [
        "currencies",
    ],
    "currency_options": [
        "currencies",
        "currency_futures",
    ],
    "currency_index_futures": [
        "currency_indices",
    ],
    "currency_index_options": [
        "currency_indices",
        "currency_index_futures",
    ],
}

RESOLVED = "resolved"

AMBIGUOUS = "ambiguous"

UNRESOLVED = "unresolved"

NO_CODE = "no_code"


class UnderlyingResolver:
    """
    Decides and records which instrument every live derivative of one mapping date is written on.

    Attributes:
        WRITE_BATCH_ROWS (int): How many rows one insert sends.
        engine (sqlalchemy.engine.Engine): The database the unified tables are read from and written to.
    """

    WRITE_BATCH_ROWS = 5000

    def __init__(self, engine=None):
        """
        Builds the resolver around a database engine.

        Args:
            engine (sqlalchemy.engine.Engine | None): The engine to use, or None for the configured one.

        Returns:
            None: This method returns nothing.
        """
        self.engine = engine or get_postgres_engine()

    def live_derivatives(self, connection, mapping_date):
        """
        Reads every future and option mapped on the date that has not expired.

        Args:
            connection (sqlalchemy.engine.Connection): The open connection.
            mapping_date (datetime.date): The mapping date.

        Returns:
            dict: Instrument id as text to a pair of its exchange and its exchange-prefixed segment.
        """
        statement = text(
            f"SELECT DISTINCT i.instrument_id, i.exchange, i.segment FROM {tables.MASTER} i "
            f"JOIN {tables.BROKER_MAPPINGS} m ON m.instrument_id = i.instrument_id AND m.mapping_date = :mapping_date "
            "WHERE i.shape IN ('future', 'option') AND i.expiry_date >= :mapping_date"
        )
        derivatives = {}
        for row in connection.execute(statement, {"mapping_date": mapping_date}):
            derivatives[str(row.instrument_id)] = (row.exchange, row.segment)
        return derivatives

    def underlying_codes(self, connection, mapping_date):
        """
        Reads the exchange code each broker gives for each derivative's underlying.

        Args:
            connection (sqlalchemy.engine.Connection): The open connection.
            mapping_date (datetime.date): The mapping date.

        Returns:
            dict: Instrument id as text to a dict of broker name to the code that broker gives.
        """
        statement = text(
            "SELECT m.instrument_id, m.broker, m.attributes->>'underlying_token' AS code "
            f"FROM {tables.BROKER_MAPPINGS} m JOIN {tables.MASTER} i ON i.instrument_id = m.instrument_id "
            "WHERE m.mapping_date = :mapping_date AND m.broker = ANY(:brokers) "
            "AND i.shape IN ('future', 'option') AND i.expiry_date >= :mapping_date "
            "AND nullif(m.attributes->>'underlying_token', '') IS NOT NULL"
        )
        codes = collections.defaultdict(dict)
        parameters = {
            "mapping_date": mapping_date,
            "brokers": CODE_BROKERS,
        }
        for row in connection.execute(statement, parameters):
            codes[str(row.instrument_id)][row.broker] = row.code
        return codes

    def candidates(self, connection, mapping_date):
        """
        Reads the exchange code of every share, index and future mapped on the date.

        Args:
            connection (sqlalchemy.engine.Connection): The open connection.
            mapping_date (datetime.date): The mapping date.

        Returns:
            dict: A triple of exchange, exchange-prefixed segment and exchange code to the set of instrument ids, as text, that carry that code there.
        """
        statement = text(
            "SELECT DISTINCT i.instrument_id, i.exchange, i.segment, "
            "CASE WHEN m.broker = ANY(:token_brokers) THEN m.broker_token "
            "ELSE m.attributes->>'underlying_token' END AS code "
            f"FROM {tables.BROKER_MAPPINGS} m JOIN {tables.MASTER} i ON i.instrument_id = m.instrument_id "
            "WHERE m.mapping_date = :mapping_date AND ("
            "(m.broker = ANY(:token_brokers) AND i.shape IN ('security', 'future')) "
            "OR (m.broker = ANY(:attribute_brokers) AND i.shape = 'security'))"
        )
        parameters = {
            "mapping_date": mapping_date,
            "token_brokers": TOKEN_CODE_BROKERS,
            "attribute_brokers": ATTRIBUTE_CODE_BROKERS,
        }
        found = collections.defaultdict(set)
        for row in connection.execute(statement, parameters):
            if row.code:
                found[(row.exchange, row.segment, row.code)].add(str(row.instrument_id))
        return found

    def decide(self, exchange, segment, codes, candidates):
        """
        Decides one derivative's underlying from the codes the brokers give for it.

        Args:
            exchange (str): The derivative's exchange.
            segment (str): The derivative's exchange-prefixed segment.
            codes (dict): Broker name to the code that broker gives, which may be empty.
            candidates (dict): The candidates, as `candidates` returns them.

        Returns:
            tuple: The underlying's instrument id as text, or None, and the status.
        """
        if not codes:
            return None, NO_CODE
        bare_segment = segment.removeprefix(f"{exchange}_")
        found = set()
        for candidate_bare in CANDIDATE_SEGMENTS.get(bare_segment, []):
            candidate_segment = f"{exchange}_{candidate_bare}"
            for code in codes.values():
                found.update(candidates.get((exchange, candidate_segment, code), set()))
        if len(found) == 1:
            return next(iter(found)), RESOLVED
        if found:
            return None, AMBIGUOUS
        return None, UNRESOLVED

    def decisions(self, mapping_date):
        """
        Decides every live derivative's underlying for the date.

        Args:
            mapping_date (datetime.date): The mapping date.

        Returns:
            list: One dictionary per derivative with `instrument_id`, `mapping_date`, `segment`, `underlying_instrument_id`, `status` and `sources`.
        """
        with self.engine.connect() as connection:
            derivatives = self.live_derivatives(connection, mapping_date)
            codes_by_derivative = self.underlying_codes(connection, mapping_date)
            candidates = self.candidates(connection, mapping_date)
        rows = []
        for instrument_id, (exchange, segment) in derivatives.items():
            codes = codes_by_derivative.get(instrument_id, {})
            underlying, status = self.decide(exchange, segment, codes, candidates)
            rows.append({
                "instrument_id": instrument_id,
                "mapping_date": mapping_date,
                "segment": segment,
                "underlying_instrument_id": underlying,
                "status": status,
                "sources": json.dumps(codes, sort_keys=True),
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
            f"DELETE FROM {tables.UNDERLYINGS} "
            "WHERE mapping_date = :mapping_date"
        )
        insert_statement = text(
            f"INSERT INTO {tables.UNDERLYINGS} "
            "(instrument_id, mapping_date, segment, underlying_instrument_id, status, sources) "
            "VALUES (CAST(:instrument_id AS uuid), :mapping_date, :segment, "
            "CAST(:underlying_instrument_id AS uuid), :status, CAST(:sources AS jsonb))"
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

    def summarise(self, rows):
        """
        Counts the decisions by segment and status.

        Args:
            rows (list): The decisions, as `decisions` returns them.

        Returns:
            collections.Counter: `(segment, status)` to the number of derivatives.
        """
        summary = collections.Counter()
        for row in rows:
            summary[(row["segment"], row["status"])] += 1
        return summary

    def run(self, mapping_date, dry_run=False):
        """
        Decides every live derivative's underlying for the date, and writes the decisions unless this is a dry run.

        Args:
            mapping_date (datetime.date): The mapping date.
            dry_run (bool): True to decide without writing anything.

        Returns:
            collections.Counter: `(segment, status)` to the number of derivatives.
        """
        rows = self.decisions(mapping_date)
        if not dry_run:
            self.write(mapping_date, rows)
        return self.summarise(rows)


class UnderlyingCommand:
    """The command line: decide a date's underlyings and print how many derivatives each segment has in each status."""

    def run(self):
        """
        Parses the arguments, runs the resolver and prints the summary.

        Returns:
            int: The exit code: 0 on success, 2 for a malformed date.
        """
        parser = argparse.ArgumentParser(
            description="Decide which instrument every live future and option is written on, for a mapping date.",
        )
        parser.add_argument(
            "--date",
            help="the mapping date, as YYYY-MM-DD. Today when omitted.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="decide and print the summary without writing unified.underlyings",
        )
        arguments = parser.parse_args()
        mapping_date = datetime.date.today()
        if arguments.date:
            try:
                mapping_date = datetime.date.fromisoformat(arguments.date)
            except ValueError:
                print(f"--date needs a date as YYYY-MM-DD, not {arguments.date!r}.")
                return 2
        summary = UnderlyingResolver().run(mapping_date, dry_run=arguments.dry_run)
        written = "not written, a dry run" if arguments.dry_run else "written to unified.underlyings"
        print(f"underlyings for {mapping_date}, {written}")
        print(f"  {'segment':<32} {'status':<12} {'derivatives':>11}")
        for segment, status in sorted(summary):
            print(f"  {segment:<32} {status:<12} {summary[(segment, status)]:>11}")
        return 0


if __name__ == "__main__":
    raise SystemExit(UnderlyingCommand().run())
