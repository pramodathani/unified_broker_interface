"""
Apply the historical candle tables to TimescaleDB.

    python -m stock_brokers.instruments.historical.utilities.sql.apply_ddl

Files under the `ddl` directory beside this one are executed in filename order, and every
statement is written to be safe to run again, so this is both the way to create the tables and
the way to pick up a later change to one.

The runner itself is the one the instrument DDL already uses - same behaviour, same single
transaction, pointed at a different directory. The broker schemas these tables live in are
created by `stock_brokers/instruments/sql/ddl/000_schemas.sql`, so that runner has to have been
run at least once first.
"""

from pathlib import Path

from stock_brokers.instruments.sql.apply_ddl import apply_all

DDL_DIRECTORY = Path(__file__).parent / "ddl"

def main():
    """Apply the historical DDL and report how many files were run."""
    print(f"Applying DDL from {DDL_DIRECTORY}\n")
    print(f"\nApplied {apply_all(DDL_DIRECTORY)} DDL file(s).")

if __name__ == "__main__":
    main()
