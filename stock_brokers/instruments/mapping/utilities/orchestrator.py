"""
Runs the mapping pass across every broker, in the one order that produces correct answers.

The order is not alphabetical and not configurable. Several adapters resolve their index names
against the `nse_equity_indices` rows already written for the same date, so the brokers publishing
a clean index vocabulary have to go first. That order is `MAPPED_BROKERS` in `segments.py`, which
is imported here rather than restated, because two lists that must agree eventually will not.

Each broker is mapped in its own try/except, so one broker's rules file being wrong does not cost
the others their mapping for the day. This matters less than it does for the download stage - the
mapping reads stored rows and can be re-run over any date, whereas a missed download is missed
forever - but a partial answer is still worth more than none.

A run covering every broker ends by merging away stale duplicate instruments, where a broker
publishes two rows for one scrip and the others agree on which is live. A run for a subset skips
that step, since a broker cannot vote on itself.
"""

import importlib

from sqlalchemy import text

from stock_brokers.instruments.mapping.utilities import collisions
from stock_brokers.instruments.mapping.utilities.segments import MAPPED_BROKERS
from utilities.configurations import get_postgres_engine

# Broker to (module, class). Imported lazily so that mapping one broker does not pay to import
# the other nine, each of which pulls in pandas and its own regular expressions.
ADAPTERS = {
    "zerodha": ("stock_brokers.instruments.mapping.zerodha", "ZerodhaMappingAdapter"),
    "dhan": ("stock_brokers.instruments.mapping.dhan", "DhanMappingAdapter"),
    "groww": ("stock_brokers.instruments.mapping.groww", "GrowwMappingAdapter"),
    "stoxkart": ("stock_brokers.instruments.mapping.stoxkart", "StoxkartMappingAdapter"),
    "flattrade": ("stock_brokers.instruments.mapping.flattrade", "FlattradeMappingAdapter"),
    "fyers": ("stock_brokers.instruments.mapping.fyers", "FyersMappingAdapter"),
    "kotak": ("stock_brokers.instruments.mapping.kotak", "KotakMappingAdapter"),
    "shoonya": ("stock_brokers.instruments.mapping.shoonya", "ShoonyaMappingAdapter"),
    "wisdom_capital": ("stock_brokers.instruments.mapping.wisdom_capital",
                       "WisdomCapitalMappingAdapter"),
    "indmoney": ("stock_brokers.instruments.mapping.indmoney", "IndMoneyMappingAdapter"),
}

def adapter_for(broker_name):
    """
    The mapping adapter class for a broker.

    Args:
        broker_name (str): The name of the broker.

    Returns:
        type: The adapter class, not an instance.

    Raises:
        ValueError: If no adapter is registered for that broker.
    """
    if broker_name not in ADAPTERS:
        raise ValueError(f"No mapping adapter for {broker_name}. "
                         f"Known: {', '.join(sorted(ADAPTERS))}")
    module_name, class_name = ADAPTERS[broker_name]
    return getattr(importlib.import_module(module_name), class_name)

def has_raw_rows(engine, broker_name, mapping_date):
    """
    Whether a broker stored any raw instrument rows for a date.

    Asked before mapping, so that a broker whose download failed is reported as absent from the
    day rather than mapped to nothing.

    Args:
        engine (sqlalchemy.engine.Engine): A SQLAlchemy engine over TimescaleDB.
        broker_name (str): The name of the broker.
        mapping_date (datetime.date): The snapshot date to look for.

    Returns:
        bool: True when at least one row is stored.
    """
    with engine.connect() as connection:
        exists = connection.execute(
            text("select to_regclass(:qualified_name) is not null"),
            {"qualified_name": f"{broker_name}.instruments"},
        ).scalar()
        if not exists:
            return False
        row = connection.execute(
            text(f"select 1 from {broker_name}.instruments where download_date = :d limit 1"),
            {"d": mapping_date},
        ).first()
    return row is not None

def report_row_errors(broker_name, errors, limit=10):
    """
    Print the distinct row errors an adapter collected, rather than only how many there were.

    Args:
        broker_name (str): The name of the broker that produced them.
        errors (list): The (segment, message) pairs from the adapter's summary.
        limit (int): The most distinct pairs to print before summarising the rest.

    Returns:
        None: This function returns nothing.
    """
    if not errors:
        return
    counts = {}
    for segment, message in errors:
        counts[(segment, message)] = counts.get((segment, message), 0) + 1
    ordered = sorted(counts.items(), key=lambda item: -item[1])
    print(f"{broker_name}: {len(errors)} row error(s) in {len(ordered)} distinct form(s):")
    for (segment, message), count in ordered[:limit]:
        print(f"    {count:>7} x [{segment}] {message}")
    if len(ordered) > limit:
        print(f"    and {len(ordered) - limit} further distinct error(s).")

def map_one(broker_name, mapping_date):
    """
    Map one broker's stored raw rows for one date, catching any failure rather than raising.

    Args:
        broker_name (str): The name of the broker to map.
        mapping_date (datetime.date): The snapshot date to map.

    Returns:
        dict: Keys "broker", "matched", "uncategorised", "instruments", "row_errors" and "error",
            where "error" is None on success. "row_errors" counts rows the adapter could not build
            an identity for; see below for why that is not the same thing as a failure.
    """
    print(f"--- {broker_name} ---")
    try:
        summary = adapter_for(broker_name)().run(mapping_date)
        # A rules file naming a column the broker does not publish raises once per row and is
        # caught per row, so the adapter returns normally with an empty segment and a very long
        # errors list. Counting them here is what stops that passing as a clean run.
        #
        # The messages are printed as well as counted, deduplicated by (segment, message), because
        # a count alone says a rules file is wrong without saying which column it named - and the
        # errors list is discarded once this returns. Thousands of rows failing usually means one
        # mistake, so the distinct set is short even when the count is not.
        report_row_errors(broker_name, summary["errors"])
        return {"broker": broker_name, "matched": summary["matched"],
                "uncategorised": summary["uncategorised"],
                "instruments": summary["instruments_upserted"],
                "row_errors": len(summary["errors"]), "error": None}
    except Exception as exception:
        message = f"{type(exception).__name__}: {str(exception).splitlines()[0]}"
        print(f"{broker_name}: FAILED with {message}")
        return {"broker": broker_name, "matched": 0, "uncategorised": 0,
                "instruments": 0, "row_errors": 0, "error": message}

def map_all(mapping_date, brokers=None, skip_collisions=False):
    """
    Map one date, for one broker, several, or every broker in the fixed processing order.

    Args:
        mapping_date (datetime.date): The snapshot date to map.
        brokers (list[str] | None): The brokers to map. None maps every broker.
        skip_collisions (bool): When True, do not run the duplicate merge afterwards.

    Returns:
        list[dict]: One result dictionary per broker attempted, in processing order.
    """
    engine = get_postgres_engine()
    requested = list(brokers) if brokers else list(MAPPED_BROKERS)
    # Reorder to the canonical processing order whatever order the caller listed them in, because
    # a later broker may need an earlier one's index rows.
    ordered = [name for name in MAPPED_BROKERS if name in requested]
    unknown = [name for name in requested if name not in MAPPED_BROKERS]
    if unknown:
        raise ValueError(f"Unknown broker(s): {', '.join(unknown)}. "
                         f"Known: {', '.join(MAPPED_BROKERS)}")

    print(f"\n=== mapping for {mapping_date} ===")
    results = []
    for broker_name in ordered:
        if not has_raw_rows(engine, broker_name, mapping_date):
            print(f"{broker_name}: no raw rows stored for {mapping_date}, skipping.")
            continue
        results.append(map_one(broker_name, mapping_date))

    print(f"\n=== mapping summary for {mapping_date} ===")
    for result in results:
        if result["error"]:
            status = result["error"]
        else:
            status = (f"{result['matched']} classified, {result['uncategorised']} uncategorised, "
                      f"{result['instruments']} instrument(s)")
            if result["row_errors"]:
                status = status + f", {result['row_errors']} ROW ERROR(S)"
        print(f"{result['broker']:<16} {status}")

    failed = [result["broker"] for result in results if result["error"]]
    if failed:
        print(f"{len(failed)} broker(s) failed to map: {', '.join(failed)}")
    with_row_errors = [result["broker"] for result in results if result["row_errors"]]
    if with_row_errors:
        print(f"{len(with_row_errors)} broker(s) had row errors, which usually means a rules file "
              f"names a column the broker does not publish: {', '.join(with_row_errors)}")

    # Every broker that actually produced rows, not every broker asked for. A date on which only
    # some brokers downloaded cannot support the merge either, and during a backfill those dates
    # are the norm rather than the exception.
    mapped_everything = len(results) == len(MAPPED_BROKERS)
    if results and mapped_everything and not skip_collisions:
        collisions.run(mapping_date)
    elif results and not mapped_everything:
        print(f"Skipping the duplicate merge: it needs every broker to have mapped, and "
              f"{len(results)} of {len(MAPPED_BROKERS)} did. One broker cannot vote on itself.")

    return results
