"""
Shared machinery for downloading a broker's daily instrument master and landing it in TimescaleDB.

Each broker subclasses `BrokerInstruments` and implements `download()`. Everything else - the
cleaning steps and the database write - is supplied here, so a broker module is only ever the
handful of lines that describe where its file lives and what shape it arrives in.

Two things about the pipeline are deliberate rather than incidental. Every file is read as text,
so no value is coerced on the way in and a broker's own formatting survives for the mapping pass
to interpret. And a column the table does not know about raises rather than being dropped, so a
broker adding a field breaks the job loudly instead of losing the field silently.
"""

import re

import pandas
from sqlalchemy import text

from utilities.configurations import get_postgres_engine

# Exchange test scrips that some brokers ship in their master files. Never tradeable.
GARBAGE_SYMBOL_PATTERNS = [
    "NSETEST",
]

def instrument_table_name(broker_name):
    """
    Table a broker's instrument snapshots are written to.

    Each broker's instruments live in that broker's own schema, beside its ticks, order_updates
    and positions tables, rather than in a shared schema keyed by a broker column.

    - `broker_name` is the name of the broker.
    """
    return f"{broker_name}.instruments"

class BrokerInstruments:
    """
    Base class for one broker's instrument master ingestion.

    A subclass sets `BROKER_NAME` and implements `download()`. The table written to is always
    `{BROKER_NAME}.instruments`, created beforehand by the DDL files under `stock_brokers/instruments/sql/ddl`.

    - `BROKER_NAME` is the lowercase broker name, which is also its PostgreSQL schema.
    - `DEDUPE_KEY_COLUMNS` are the normalized column names forming this broker's natural key. An
      empty list disables de-duplication.
    - `DEDUPE_SORT_COLUMN` is sorted on before de-duplicating, so the row kept is predictable
      rather than whichever the broker happened to list first.
    """

    BROKER_NAME = ""
    DEDUPE_KEY_COLUMNS = []
    DEDUPE_SORT_COLUMN = None

    def __init__(self):
        """
        Build the broker ingester and its database engine.

        The engine is lazy and opens no connection until a query runs, so `download()` and the
        cleaning steps can be exercised without a database.
        """
        if not self.BROKER_NAME:
            raise NotImplementedError(f"{type(self).__name__} must set BROKER_NAME")
        self.engine = get_postgres_engine()
        self.table = instrument_table_name(self.BROKER_NAME)

    def download(self):
        """
        Fetch this broker's instrument master file or files.

        A subclass must override this. Every file is read as text so that nothing is coerced on
        the way in, and a broker shipping several files returns them already concatenated.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement download()")

    def normalize_columns(self, frame):
        """
        Rewrite column names into a stable lowercase form usable as a SQL identifier.

        Some brokers bake stray whitespace and punctuation into the header itself rather than it
        being a parsing artifact, so the raw name is not safe to key on.

        - `frame` is the frame whose column names are to be normalized.
        """
        def clean(name):
            name = re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip())
            return name.strip("_").lower()

        frame = frame.copy()
        frame.columns = [clean(column) for column in frame.columns]
        return frame

    def strip_whitespace(self, frame):
        """
        Remove leading and trailing whitespace from every text column.

        Brokers intermittently pad text fields, so the same value can arrive padded one day and
        bare the next.

        - `frame` is the frame to strip.
        """
        frame = frame.copy()
        for column in frame.columns:
            if frame[column].dtype == object:
                frame[column] = frame[column].str.strip()
        return frame

    def drop_unnamed_columns(self, frame):
        """
        Drop the empty placeholder columns a trailing delimiter on every line creates.

        A column is only dropped when it is empty on every row. One carrying real values is kept
        and reported instead, so nothing is discarded silently.

        - `frame` is the frame to examine.
        """
        frame = frame.copy()
        for column in [c for c in frame.columns if re.match(r"^unnamed(_\d+)?$", c)]:
            populated = frame[column].notna() & (frame[column].astype(str).str.strip() != "")
            if populated.any():
                print(f"{self.BROKER_NAME}: column '{column}' looks like a parsing artifact but holds "
                      f"{int(populated.sum())} value(s), keeping it.")
                continue
            frame = frame.drop(columns=[column])
            print(f"{self.BROKER_NAME}: dropped empty artifact column '{column}'.")
        return frame

    def drop_garbage_rows(self, frame):
        """
        Drop the placeholder instruments some brokers ship in their master files.

        - `frame` is the frame to filter.
        """
        if frame.empty:
            return frame
        matches = pandas.Series(False, index=frame.index)
        for column in frame.columns:
            if frame[column].dtype == object:
                for pattern in GARBAGE_SYMBOL_PATTERNS:
                    matches = matches | frame[column].astype(str).str.contains(pattern, case=False, na=False)
        dropped = int(matches.sum())
        if dropped:
            print(f"{self.BROKER_NAME}: dropped {dropped} placeholder row(s) matching {GARBAGE_SYMBOL_PATTERNS}.")
        return frame[~matches].reset_index(drop=True)

    def dedupe(self, frame):
        """
        Drop rows repeating this broker's natural key.

        - `frame` is the frame to de-duplicate.
        """
        if not self.DEDUPE_KEY_COLUMNS:
            return frame
        if self.DEDUPE_SORT_COLUMN and self.DEDUPE_SORT_COLUMN in frame.columns:
            frame = frame.sort_values(by=self.DEDUPE_SORT_COLUMN, kind="stable",
                                      key=lambda column: column.astype(str))
        before = len(frame)
        frame = frame.drop_duplicates(subset=self.DEDUPE_KEY_COLUMNS, keep="first").reset_index(drop=True)
        dropped = before - len(frame)
        if dropped:
            print(f"{self.BROKER_NAME}: dropped {dropped} duplicate row(s) on {self.DEDUPE_KEY_COLUMNS}.")
        return frame

    def table_columns(self):
        """
        The column names of this broker's table as it currently exists in the database.

        The live table is the single source of truth for its own shape: the DDL lives in
        `stock_brokers/instruments/sql/ddl` and nothing in Python restates it.
        """
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("select column_name from information_schema.columns "
                     "where table_schema = :schema and table_name = 'instruments' "
                     "order by ordinal_position"),
                {"schema": self.BROKER_NAME},
            ).all()
        if not rows:
            raise ValueError(f"Table {self.table} does not exist. Run 'python -m stock_brokers.instruments.sql.apply_ddl' first.")
        return [row[0] for row in rows]

    def has_data_for(self, download_date):
        """
        Whether this broker's table already holds a snapshot for a given date.

        - `download_date` is the snapshot date to look for.
        """
        with self.engine.connect() as connection:
            exists = connection.execute(
                text("select to_regclass(:qualified_name) is not null"),
                {"qualified_name": self.table},
            ).scalar()
            if not exists:
                return False
            row = connection.execute(
                text(f"select 1 from {self.table} where download_date = :download_date limit 1"),
                {"download_date": download_date},
            ).first()
        return row is not None

    def ingest(self, download_date=None, bootstrap=False):
        """
        Download, clean and store one day's instrument master for this broker.

        Re-running for a date already stored is a no-op unless `bootstrap` is set, so the daily
        job is safe to run twice.

        - `download_date` is the snapshot date to record, defaulting to today.
        - `bootstrap` replaces that date's stored rows rather than skipping.
        """
        download_date = download_date or pandas.Timestamp.today().date()
        already_stored = self.has_data_for(download_date)
        if already_stored and not bootstrap:
            print(f"{self.BROKER_NAME}: already ingested for {download_date}, skipping.")
            return 0

        print(f"{self.BROKER_NAME}: downloading instruments for {download_date} ...")
        frame = self.download()
        frame = self.normalize_columns(frame)
        frame = self.strip_whitespace(frame)
        frame = self.drop_unnamed_columns(frame)
        frame = self.drop_garbage_rows(frame)
        frame = self.dedupe(frame)
        frame["download_date"] = download_date

        unknown_columns = [column for column in frame.columns if column not in self.table_columns()]
        if unknown_columns:
            raise ValueError(
                f"{self.BROKER_NAME}: the downloaded file carries column(s) {unknown_columns} that "
                f"{self.table} does not have. Add them to the DDL rather than dropping them.")

        if already_stored:
            with self.engine.begin() as connection:
                deleted = connection.execute(
                    text(f"delete from {self.table} where download_date = :download_date"),
                    {"download_date": download_date},
                ).rowcount
            print(f"{self.BROKER_NAME}: removed {deleted} existing row(s) for {download_date} before re-ingesting.")

        frame.to_sql("instruments", self.engine, schema=self.BROKER_NAME,
                     if_exists="append", index=False, chunksize=10000)
        print(f"{self.BROKER_NAME}: ingested {len(frame)} row(s) for {download_date}.")
        return len(frame)

    def check_row_count_deviation(self, download_date, threshold=0.10):
        """
        Compare a day's row count against the average of every earlier day.

        A large swing usually means the broker's file came back truncated or unexpectedly bloated.
        This reports and never raises: a deviation is a signal to investigate, not a failure.

        - `download_date` is the snapshot date to check.
        - `threshold` is the allowed fractional deviation, so 0.10 permits ten percent either way.
        """
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(f"select download_date, count(*) from {self.table} group by download_date")).all()

        counts_by_date = {row[0]: row[1] for row in rows}
        current_rows = counts_by_date.get(download_date)
        if current_rows is None:
            message = f"INFO: {self.BROKER_NAME}: no rows stored for {download_date}, nothing to check."
            print(message)
            return {"broker": self.BROKER_NAME, "alarm": False, "message": message}

        earlier_counts = [count for date, count in counts_by_date.items() if date < download_date]
        if not earlier_counts:
            message = (f"INFO: {self.BROKER_NAME}: {current_rows} row(s) for {download_date}, "
                       f"no earlier day to compare against yet.")
            print(message)
            return {"broker": self.BROKER_NAME, "alarm": False, "message": message,
                    "current_rows": current_rows}

        average_rows = sum(earlier_counts) / len(earlier_counts)
        lower_limit = average_rows * (1 - threshold)
        upper_limit = average_rows * (1 + threshold)
        is_alarm = current_rows < lower_limit or current_rows > upper_limit
        deviation_percent = (current_rows - average_rows) / average_rows * 100

        message = (
            f"{'ALARM' if is_alarm else 'OK'}: {self.BROKER_NAME}: {current_rows} row(s) for "
            f"{download_date}, average {average_rows:.0f} over {len(earlier_counts)} earlier day(s), "
            f"deviation {deviation_percent:.2f}%, allowed range [{lower_limit:.0f}, {upper_limit:.0f}].")
        print(message)
        return {"broker": self.BROKER_NAME, "alarm": is_alarm, "message": message,
                "current_rows": current_rows, "average_rows": average_rows,
                "earlier_days": len(earlier_counts), "deviation_percent": deviation_percent}
