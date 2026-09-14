"""
Download each broker's instrument master and append today's snapshot to `{broker}.instruments`.

Safe to run daily: a broker already ingested for a date is skipped unless --bootstrap is given.
Run `python -m stock_brokers.instruments.sql.apply_ddl` first if the tables do not exist yet.

    python -m test_runs.download_instruments                      # every broker
    python -m test_runs.download_instruments zerodha dhan         # only these
    python -m test_runs.download_instruments --bootstrap zerodha  # replace today's snapshot
"""

import sys

from stock_brokers.instruments.orchestrator import ingest_all, INSTRUMENT_BROKERS

def main():
    """Download the requested brokers' instrument masters and report what each one stored."""
    arguments = sys.argv[1:]
    bootstrap = "--bootstrap" in arguments
    if bootstrap:
        arguments.remove("--bootstrap")
    brokers = arguments or list(INSTRUMENT_BROKERS)

    unknown = [broker for broker in brokers if broker not in INSTRUMENT_BROKERS]
    if unknown:
        print(f"Unknown broker(s): {', '.join(unknown)}")
        print(f"Known: {', '.join(INSTRUMENT_BROKERS)}")
        return 1

    print(f"Downloading instruments for {len(brokers)} broker(s)"
          f"{', replacing today\'s snapshot' if bootstrap else ''}.\n")
    results = ingest_all(brokers, bootstrap=bootstrap)

    print("\nSummary")
    failures = 0
    for broker_name, (rows, deviation, error) in results.items():
        if error:
            failures += 1
            print(f"  {broker_name:<16} FAILED   {error}")
        else:
            alarm = "  ALARM" if deviation and deviation.get('alarm') else ""
            print(f"  {broker_name:<16} {rows:>9,} row(s){alarm}")
    if failures:
        print(f"\n{failures} of {len(results)} broker(s) failed.")
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
