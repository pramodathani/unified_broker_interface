"""
Apply the unified instrument tables to TimescaleDB.

    python -m stock_brokers.instruments.mapping.utilities.sql.apply_ddl

Files under the `ddl` directory beside this one are executed in filename order, and every
statement is written to be safe to run again, so this is both the way to create the tables and
the way to pick up a later change to one. The order matters for one reason: `100` creates the
`unified` schema, and `unified.broker_mappings` carries a foreign key to `unified.instruments`, so
`110` has to have run before `120`. `bin/unified/instruments/map` applies them before every run.

The runner itself is the one the instrument DDL already uses - same behaviour, same single
transaction, pointed at a different directory. These tables live in a schema of their own, so this
runner does not depend on the per-broker schema file having been applied first. The mapping will not
find anything to read until it has been, of course, but that is a question about data rather than
about DDL.
"""

from pathlib import Path

from stock_brokers.instruments.sql.apply_ddl import apply_all

DDL_DIRECTORY = Path(__file__).parent / "ddl"

def main():
    """Apply the mapping DDL and report how many files were run."""
    print(f"Applying DDL from {DDL_DIRECTORY}\n")
    print(f"\nApplied {apply_all(DDL_DIRECTORY)} DDL file(s).")

if __name__ == "__main__":
    main()
