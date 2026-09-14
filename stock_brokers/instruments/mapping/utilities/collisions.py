"""
Merge away stale duplicate instruments, using the other brokers to say which of two names is the live one.

    python -m stock_brokers.instruments.mapping.utilities.collisions
    python -m stock_brokers.instruments.mapping.utilities.collisions --date 2026-09-09
    python -m stock_brokers.instruments.mapping.utilities.collisions --date 2026-09-09 --dry-run
    python -m stock_brokers.instruments.mapping.utilities.collisions --date 2026-09-09 --delete-ties

A broker's token space is per exchange segment rather than global, so one number meaning different things in different segments is expected and is never touched here. What is worth acting on is a broker publishing two rows for one scrip inside a single namespace of its own: Flattrade lists BSE token 500040 twice, once as CENTURYTEX and once as ABREL, which are the old and the new name of one company after a rename. Both rows carry a real symbol and both hash to a valid identity, so the mapping cannot tell them apart on its own and ends up with a live instrument and a ghost.

Two tests have to agree before anything is merged, because each one alone produces false positives.

The first is the broker's own raw file. A collision only counts when that broker lists the token more than once inside one of its own token namespaces, which is the exchange and segment columns named in TOKEN_NAMESPACES. Without this test the pass also fires on Stoxkart's NSE cash and NSE currency derivatives rows, which share a token number, both land in nse_fixed_income because the canonical vocabulary has one nse exchange, and are two genuinely different government bonds. Those appear once per namespace rather than twice within one, so this test excludes them.

The second is the other brokers. For each colliding instrument, count how many other brokers mapped that same identity on the same date, and keep the one carried by strictly more of them than any rival. Nine brokers call BSE 500040 ABREL and none has heard of CENTURYTEX, so that vote is unanimous, but a stale name is often still carried by one or two brokers whose files have the same rename lag: NSE token 1467 is JSWDULUX at nine brokers and AKZOINDIA at one. A majority settles both shapes, where a rule requiring every rival to have no support at all would settle only the first.

When that count ties, a narrower one breaks it: how many other brokers carry the identity under this same token. BSE token 530565 is why. Flattrade carries both POPEES and KOIYAIN on it, Stoxkart carries KOIYAIN on it, and Stoxkart carries POPEES on a different token, because POPEES is a real company on another scrip code. Counted anywhere the vote is one against one; counted on this token it is one against zero, and the narrower count is the one that says which name belongs to this scrip.

Nothing is merged when both counts are level, since there is then no evidence to prefer either. Those are reported and left alone, because a wrong merge is worse than a duplicate, which the segment filter and the cache's candidate list already handle correctly. Passing --delete-ties merges them anyway, keeping the lowest instrument id; that last choice is arbitrary rather than reasoned, so it is opt in and the daily job never uses it. No mapped date currently needs it.

Merging deletes the unsupported broker mapping rows, never the master rows. The supported instrument is already mapped by this broker under this token, so what remains is one token pointing at one instrument, which is the case the coverage report already describes as a broker listing one instrument on several rows. Master rows stay because they are a dated record of what was seen and because a past date may still map them.

This runs as the last step of the daily mapping, after every broker, because it cannot ask a broker anything until that broker is written. It is safe to repeat, and re-mapping a single broker afterwards brings that broker's duplicates back until it is run again.
"""

import argparse
import datetime

from sqlalchemy import text

from stock_brokers.instruments.mapping.utilities import tables
from utilities.configurations import get_postgres_engine

TOKEN_NAMESPACES = {
    "zerodha": ("instrument_token", ["exchange"]),
    "dhan": ("security_id", ["exch_id", "segment"]),
    "groww": ("exchange_token", ["exchange", "segment"]),
    "stoxkart": ("token", ["exchange", "market_segment_id"]),
    "flattrade": ("token", ["exchange"]),
    "fyers": ("fytoken", ["exchange", "segment"]),
    "kotak": ("psymbol", ["pexchseg"]),
    "shoonya": ("token", ["exchange"]),
    "wisdom_capital": ("exchangeinstrumentid", ["exchangesegment"]),
    "indmoney": ("security_id", ["exch", "segment"]),
}


def latest_mapping_date(engine):
    """
    The most recent date anything was mapped on.

    Args:
        engine (sqlalchemy.engine.Engine): A SQLAlchemy engine over TimescaleDB.

    Returns:
        datetime.date | None: The latest mapping date, or None when nothing has been mapped.
    """
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT max(mapping_date) FROM {tables.BROKER_MAPPINGS}")).scalar()


def read_collisions(engine, mapping_date):
    """
    Read every token that points at more than one instrument inside a single segment, with each candidate's cross-broker support.

    Each candidate carries two counts. Its support is the number of other brokers that mapped the same instrument identity anywhere on the same date, which is the evidence used to tell a live instrument from a stale alias of one. Its token support is the narrower number that mapped that identity under this same token, which is what separates two real companies whose names have both been attached to one scrip code.

    Args:
        engine (sqlalchemy.engine.Engine): A SQLAlchemy engine over TimescaleDB.
        mapping_date (datetime.date): The mapping date to examine.

    Returns:
        dict: Keyed by the tuple (broker, segment, broker_token), each value a list of (instrument_id, supporters, token_supporters) tuples ordered by instrument id.
    """
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "WITH collided AS ("
                "  SELECT b.broker, m.segment, b.broker_token "
                f"  FROM {tables.BROKER_MAPPINGS} b "
                f"  JOIN {tables.MASTER} m ON m.instrument_id = b.instrument_id "
                "  WHERE b.mapping_date = :d "
                "  GROUP BY 1, 2, 3 HAVING count(DISTINCT b.instrument_id) > 1"
                "), candidates AS ("
                "  SELECT c.broker, c.segment, c.broker_token, b.instrument_id "
                "  FROM collided c "
                f"  JOIN {tables.BROKER_MAPPINGS} b "
                "    ON b.broker = c.broker AND b.broker_token = c.broker_token AND b.mapping_date = :d "
                f"  JOIN {tables.MASTER} m "
                "    ON m.instrument_id = b.instrument_id AND m.segment = c.segment"
                ") "
                "SELECT c.broker, c.segment, c.broker_token, c.instrument_id, "
                f"       (SELECT count(DISTINCT o.broker) FROM {tables.BROKER_MAPPINGS} o "
                "        WHERE o.instrument_id = c.instrument_id AND o.mapping_date = :d "
                "          AND o.broker <> c.broker) AS supporters, "
                f"       (SELECT count(DISTINCT o.broker) FROM {tables.BROKER_MAPPINGS} o "
                "        WHERE o.instrument_id = c.instrument_id AND o.mapping_date = :d "
                "          AND o.broker <> c.broker AND o.broker_token = c.broker_token) "
                "         AS token_supporters "
                "FROM candidates c "
                "ORDER BY c.broker, c.segment, c.broker_token, c.instrument_id"
            ),
            {
                "d": mapping_date,
            },
        ).all()

    collisions = {}
    for row in rows:
        key = (
            row.broker,
            row.segment,
            row.broker_token,
        )
        if key not in collisions:
            collisions[key] = []
        collisions[key].append((str(row.instrument_id), row.supporters, row.token_supporters))
    return collisions


def repeated_tokens(engine, mapping_date, broker, broker_tokens):
    """
    Of a broker's tokens, the ones its own raw file lists more than once inside one of its token namespaces.

    A token appearing once in each of two namespaces is that broker numbering its markets separately and is not a duplicate. A token appearing twice inside one namespace is the broker publishing two rows for one scrip, which is the only case this module acts on.

    Args:
        engine (sqlalchemy.engine.Engine): A SQLAlchemy engine over TimescaleDB.
        mapping_date (datetime.date): The snapshot date of the raw rows to read.
        broker (str): The broker whose raw table to read.
        broker_tokens (list[str]): The tokens to test.

    Returns:
        set: The subset of broker_tokens that repeat inside one namespace.
    """
    if not broker_tokens:
        return set()

    token_column, namespace_columns = TOKEN_NAMESPACES[broker]
    parts = []
    for column in namespace_columns:
        parts.append(f"coalesce({column}::text, '')")
    namespace = " || '|' || ".join(parts)

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                f"SELECT {token_column}::text AS token FROM {broker}.instruments "
                f"WHERE download_date = :d AND {token_column}::text = ANY(:tokens) "
                f"GROUP BY {token_column}::text, {namespace} HAVING count(*) > 1"
            ),
            {
                "d": mapping_date,
                "tokens": list(broker_tokens),
            },
        ).all()

    repeated = set()
    for row in rows:
        repeated.add(row.token)
    return repeated


def decide(candidates, break_ties=False):
    """
    Decide which of one collision's candidates survives and which are merged into it.

    The candidate carried by strictly more other brokers than any of its rivals wins. Requiring every rival to have no support at all would be too blunt: a stale name is often still carried by one or two other brokers whose files have the same rename lag, so nine brokers against one would be left unsettled beside a genuine one against one.

    When that count ties, token support breaks it: the candidate another broker maps under this same token is the one that belongs to this scrip. BSE token 530565 is the case this exists for. Flattrade carries both POPEES and KOIYAIN on it, Stoxkart carries KOIYAIN on it, and Stoxkart also carries POPEES on a different token entirely, because POPEES is a real company on another scrip code. Counting identities anywhere makes that one against one; counting them on this token makes it one against zero, and the second count is the one telling the truth about which name belongs here.

    Args:
        candidates (list): The (instrument_id, supporters, token_supporters) tuples of one collision.
        break_ties (bool): When True, settle a collision that both counts leave level by keeping the lowest instrument id rather than declining. That last choice is arbitrary and only deterministic, so this is opt in.

    Returns:
        tuple: (keep, merge), where keep is the surviving instrument id or None when the evidence does not settle the collision, and merge is the list of instrument ids to delete.
    """
    ranked = sorted(candidates, key=lambda candidate: (-candidate[1], -candidate[2], candidate[0]))
    best_identifier, best_supporters, best_token_supporters = ranked[0]

    if not break_ties:
        if best_supporters == 0:
            return None, []
        if len(ranked) > 1:
            rival_supporters = ranked[1][1]
            rival_token_supporters = ranked[1][2]
            if rival_supporters == best_supporters and rival_token_supporters == best_token_supporters:
                return None, []

    merge = []
    for instrument_identifier, supporters, token_supporters in candidates:
        if instrument_identifier != best_identifier:
            merge.append(instrument_identifier)
    return best_identifier, merge


def describe(engine, instrument_identifiers):
    """
    Read a readable name for each instrument, for the report this pass prints.

    Args:
        engine (sqlalchemy.engine.Engine): A SQLAlchemy engine over TimescaleDB.
        instrument_identifiers (list[str]): The instrument ids to name.

    Returns:
        dict: Instrument id to a display name, falling back to the id itself.
    """
    if not instrument_identifiers:
        return {}

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT instrument_id, coalesce(symbol, underlying_symbol) AS name "
                f"FROM {tables.MASTER} WHERE instrument_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {
                "ids": [str(identifier) for identifier in instrument_identifiers],
            },
        ).all()

    names = {}
    for row in rows:
        names[str(row.instrument_id)] = row.name or str(row.instrument_id)
    return names


def delete_mappings(engine, mapping_date, deletions):
    """
    Delete the merged broker mapping rows, all of them in one transaction.

    Args:
        engine (sqlalchemy.engine.Engine): A SQLAlchemy engine over TimescaleDB.
        mapping_date (datetime.date): The mapping date to delete from.
        deletions (list): Tuples of (broker, broker_token, instrument_id) to remove.

    Returns:
        int: The number of rows deleted.
    """
    if not deletions:
        return 0

    deleted = 0
    with engine.begin() as connection:
        for broker, broker_token, instrument_identifier in deletions:
            result = connection.execute(
                text(
                    f"DELETE FROM {tables.BROKER_MAPPINGS} "
                    "WHERE broker = :b AND broker_token = :t AND mapping_date = :d "
                    "  AND instrument_id = CAST(:i AS uuid)"
                ),
                {
                    "b": broker,
                    "t": broker_token,
                    "d": mapping_date,
                    "i": instrument_identifier,
                },
            )
            deleted += result.rowcount
    return deleted


def duplicates_in_broker_files(engine, mapping_date, collisions):
    """
    Narrow the collisions to the ones a broker's own raw file actually repeats within one namespace.

    Args:
        engine (sqlalchemy.engine.Engine): A SQLAlchemy engine over TimescaleDB.
        mapping_date (datetime.date): The mapping date the collisions belong to.
        collisions (dict): The collisions read by read_collisions.

    Returns:
        tuple: (duplicates, namespaced), two lists of collision keys, the first being real duplicates in the broker's file and the second being tokens the broker numbers separately per market.
    """
    tokens_by_broker = {}
    for broker, segment, broker_token in collisions:
        if broker not in tokens_by_broker:
            tokens_by_broker[broker] = set()
        tokens_by_broker[broker].add(broker_token)

    repeated_by_broker = {}
    for broker in tokens_by_broker:
        repeated_by_broker[broker] = repeated_tokens(engine, mapping_date, broker, sorted(tokens_by_broker[broker]))

    duplicates = []
    namespaced = []
    for key in sorted(collisions):
        broker, segment, broker_token = key
        if broker_token in repeated_by_broker[broker]:
            duplicates.append(key)
        else:
            namespaced.append(key)
    return duplicates, namespaced


def run(mapping_date=None, dry_run=False, break_ties=False):
    """
    Merge one date's stale duplicate instruments away and report what was done.

    Args:
        mapping_date (datetime.date | None): The date to resolve. Defaults to the latest mapped date.
        dry_run (bool): When True, report the decisions without deleting anything.
        break_ties (bool): When True, also merge the collisions where the vote is tied, keeping the lowest instrument id. The choice is arbitrary, so this is never on by default and never on in the daily job.

    Returns:
        dict: Keys "collisions", "duplicates", "merged", "unsettled" and "deleted".

    Raises:
        SystemExit: If nothing has been mapped and no date was given.
    """
    engine = get_postgres_engine()
    if mapping_date is None:
        mapping_date = latest_mapping_date(engine)
    if mapping_date is None:
        raise SystemExit("nothing has been mapped, so there are no duplicates to merge.")

    print("")
    print(f"=== merging duplicate instruments for {mapping_date} ===")
    collisions = read_collisions(engine, mapping_date)
    if not collisions:
        print("no token points at more than one instrument inside a single segment.")
        return {
            "collisions": 0,
            "duplicates": 0,
            "merged": 0,
            "unsettled": 0,
            "deleted": 0,
        }

    duplicates, namespaced = duplicates_in_broker_files(engine, mapping_date, collisions)
    print(f"{len(collisions)} token(s) point at more than one instrument inside one segment:")
    print(f"  {len(namespaced):>8} the broker numbers separately per market   left alone")
    print(f"  {len(duplicates):>8} the broker's own file repeats the token     candidates to merge")

    deletions = []
    settled = []
    unsettled = []
    for key in duplicates:
        broker, segment, broker_token = key
        keep, merge = decide(collisions[key], break_ties)
        if keep is None:
            unsettled.append(key)
            continue
        settled.append((key, keep, merge))
        for instrument_identifier in merge:
            deletions.append((broker, broker_token, instrument_identifier))

    named = []
    for key, keep, merge in settled:
        named.append(keep)
        named.extend(merge)
    names = describe(engine, named)

    print("")
    print(f"{len(settled)} settled by the other brokers, {len(unsettled)} with no usable vote.")
    if settled:
        print("")
        print("first 20 settled:")
        for key, keep, merge in settled[:20]:
            broker, segment, broker_token = key
            dropped = ", ".join(names.get(identifier, identifier) for identifier in merge)
            print(f"  {broker:<16} {broker_token:<14} {segment:<22} kept {names.get(keep, keep)}, merged {dropped}")
    if unsettled:
        print("")
        print("left alone, where the vote is tied and --delete-ties was not given:")
        for key in unsettled[:20]:
            broker, segment, broker_token = key
            identifiers = []
            for instrument_identifier, supporters, token_supporters in collisions[key]:
                identifiers.append(instrument_identifier)
            unsettled_names = describe(engine, identifiers)
            listed = ", ".join(unsettled_names.get(identifier, identifier) for identifier in identifiers)
            print(f"  {broker:<16} {broker_token:<14} {segment:<22} {listed}")

    print("")
    if dry_run:
        deleted = 0
        print(f"dry run: {len(deletions)} broker mapping row(s) would be merged away.")
    else:
        deleted = delete_mappings(engine, mapping_date, deletions)
        print(f"{deleted} broker mapping row(s) merged away.")

    return {
        "collisions": len(collisions),
        "duplicates": len(duplicates),
        "merged": len(settled),
        "unsettled": len(unsettled),
        "deleted": deleted,
    }


def main():
    """
    Parse the command line arguments and merge the duplicates.

    Returns:
        None: This function returns nothing.
    """
    parser = argparse.ArgumentParser(
        description="Merge stale duplicate instruments away using cross-broker confirmation."
    )
    parser.add_argument("--date", help="Mapping date to resolve, as YYYY-MM-DD. Defaults to the latest mapped date.")
    parser.add_argument("--dry-run", action="store_true", help="Report the decisions without deleting anything.")
    parser.add_argument(
        "--delete-ties",
        action="store_true",
        help="Also merge collisions where the vote is tied, keeping the lowest instrument id. The choice is arbitrary.",
    )
    arguments = parser.parse_args()

    mapping_date = None
    if arguments.date:
        mapping_date = datetime.date.fromisoformat(arguments.date)
    run(mapping_date, arguments.dry_run, arguments.delete_ties)


if __name__ == "__main__":
    main()
