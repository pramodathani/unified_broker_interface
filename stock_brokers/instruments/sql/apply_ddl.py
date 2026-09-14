"""
Apply every schema and table definition to TimescaleDB.

Files under `stock_brokers/instruments/sql/ddl` are executed in filename order, so the numeric prefix decides what is
created first - schemas before the tables that live in them. Every statement is written to be
safe to run again, which makes this both the way to create the tables and the way to pick up a
later change to one.

    python -m stock_brokers.instruments.sql.apply_ddl
"""

from pathlib import Path

from sqlalchemy import text

from utilities.configurations import get_postgres_engine

DDL_DIRECTORY = Path(__file__).parent / "ddl"

def apply_all(directory=DDL_DIRECTORY):
    """
    Execute every DDL file in filename order.

    The whole run is one transaction: a broken definition rolls the batch back rather than
    leaving the database half migrated.

    - `directory` is the folder holding the `.sql` files.
    """
    if not directory.is_dir():
        raise FileNotFoundError(f"No DDL directory at {directory}")

    paths = sorted(directory.glob("*.sql"))
    with get_postgres_engine().begin() as connection:
        for path in paths:
            connection.execute(text(path.read_text()))
            print(f"  applied {path.name}")
    return len(paths)

def main():
    """Apply the DDL and report how many files were run."""
    print(f"Applying DDL from {DDL_DIRECTORY}\n")
    print(f"\nApplied {apply_all()} DDL file(s).")

if __name__ == "__main__":
    main()
