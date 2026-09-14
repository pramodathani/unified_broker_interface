"""
Populate the Redis tier of the instrument mapping cache for one mapping date.

    python -m stock_brokers.instruments.mapping.utilities.warm_cache
    python -m stock_brokers.instruments.mapping.utilities.warm_cache --date 2026-09-08 --clear

This runs once a day, straight after the instrument mapping it caches, and exists so that no process ever has to pay Postgres or a bulk load for a mapping that every process wants. Without it the cache still works, filling itself from Postgres as processes touch instruments; with it, the first process of the morning is already fast.

Three passes stream out of Postgres and write in pipelined batches, so the command's memory stays flat rather than holding the 829 megabytes the whole map costs in one process. The key naming the current date is written last, so a reader sees either the previous complete day or the new complete day and never a half written one.

Every field written goes through the same ``MappingRedisTier`` the cache reads through, and every row is built by the same ``MappingPostgresTier`` methods the cache's own fall-through uses. That is deliberate. Were this command to encode the fields itself, a change to the reader's shape, such as the four field order handle, not made here as well would leave Redis holding a value that decodes successfully into something no caller could use.
"""

import argparse
import datetime

from stock_brokers.instruments.mapping.utilities.cache import MappingPostgresTier, MappingRedisTier
from stock_brokers.instruments.mapping.utilities.segments import MAPPED_BROKERS


class CacheWarmer:
    """
    Fills the Redis tier of the instrument mapping cache for one mapping date.

    Attributes:
        WRITE_BATCH_FIELDS (int): How many hash fields are accumulated before a pipelined write, so that only one batch is ever in memory.
        mapping_date (datetime.date): The date being warmed.
        redis_tier (stock_brokers.instruments.mapping.utilities.cache.MappingRedisTier): The hashes being written, read and written through one class.
        postgres_tier (stock_brokers.instruments.mapping.utilities.cache.MappingPostgresTier): The streaming reads the fields are built from.
        expiry_seconds (int): How long every hash written by this run may live, computed once for the whole command.
    """

    WRITE_BATCH_FIELDS = 5000

    def __init__(self, mapping_date=None, engine=None, redis_connection=None):
        """
        Build the warmer and settle the date it will warm.

        Args:
            mapping_date (datetime.date | None): The mapping date to warm. None uses the latest date anything was mapped on.
            engine (sqlalchemy.engine.Engine): A SQLAlchemy engine over TimescaleDB. None builds one from the environment.
            redis_connection (stock_brokers.instruments.mapping.utilities.cache.MappingRedisConnection | None): The Redis connection to write through. None builds one.

        Returns:
            None: This function returns nothing.

        Raises:
            SystemExit: If no date was given and nothing has ever been mapped.
        """
        self.postgres_tier = MappingPostgresTier(engine)
        self.redis_tier = MappingRedisTier(redis_connection)

        self.mapping_date = mapping_date or self.postgres_tier.latest_mapping_date()
        if self.mapping_date is None:
            raise SystemExit("nothing has been mapped, so there is nothing to warm.")
        self.expiry_seconds = self.redis_tier.seconds_until_midnight()

    def warm_identities(self):
        """
        Write the identity of every instrument mapped on the date, keyed by instrument id.

        The identity is stored once per instrument rather than once per token, because several brokers' tokens point at one instrument and storing it per token would repeat it about twice over.

        Returns:
            int: The number of identities written.
        """
        key = self.redis_tier.identity_key(self.mapping_date)
        written = 0
        fields = {}
        for identity in self.postgres_tier.stream_identities(self.mapping_date):
            fields[identity["instrument_id"]] = self.redis_tier.encode_identity(identity)
            if len(fields) >= self.WRITE_BATCH_FIELDS:
                written += self.redis_tier.write_fields(key, fields, self.expiry_seconds)
                fields = {}
        written += self.redis_tier.write_fields(key, fields, self.expiry_seconds)
        return written

    def warm_broker_tokens(self, broker):
        """
        Write one broker's tokens for the date, each pointing at every instrument it carries.

        Every candidate is written rather than the one the tie-break picks, because a segment-filtered look-up and an unfiltered one of the same token have different right answers and must not contaminate each other. The rows arrive in tie-break order, so the first candidate stored is the unfiltered answer.

        Args:
            broker (str): The broker name, for example "zerodha".

        Returns:
            int: The number of tokens written.
        """
        key = self.redis_tier.tokens_key(self.mapping_date, broker)
        written = 0
        fields = {}
        current_token = None
        current_identifiers = []
        for broker_token, instrument_identifier in self.postgres_tier.stream_broker_tokens(self.mapping_date, broker):
            if broker_token != current_token:
                if current_token is not None:
                    fields[current_token] = ",".join(current_identifiers)
                current_token = broker_token
                current_identifiers = []
            current_identifiers.append(instrument_identifier)
            if len(fields) >= self.WRITE_BATCH_FIELDS:
                written += self.redis_tier.write_fields(key, fields, self.expiry_seconds)
                fields = {}
        if current_token is not None:
            fields[current_token] = ",".join(current_identifiers)
        written += self.redis_tier.write_fields(key, fields, self.expiry_seconds)
        return written

    def warm_order_handles(self):
        """
        Write every instrument's order handles for the date, keyed by instrument id.

        This is the direction an order needs: given an instrument, what to send to which broker. A handle carries the broker's token, the tradeable symbol, the lot size and the tick size, because all four come out of one row and an order needs all four.

        The handle is built by the same MappingPostgresTier method the cache's own fall-through uses and encoded by the same MappingRedisTier method the cache reads back, which is what keeps a warmed entry and a lazily filled one the same shape.

        Returns:
            int: The number of instruments written.
        """
        key = self.redis_tier.order_handles_key(self.mapping_date)
        written = 0
        fields = {}
        current_instrument = None
        current_handles = {}
        for instrument_identifier, broker, handle in self.postgres_tier.stream_order_handles(self.mapping_date):
            if instrument_identifier != current_instrument:
                if current_instrument is not None:
                    fields[current_instrument] = self.redis_tier.encode_order_handles(current_handles)
                current_instrument = instrument_identifier
                current_handles = {}
            current_handles[broker] = handle
            if len(fields) >= self.WRITE_BATCH_FIELDS:
                written += self.redis_tier.write_fields(key, fields, self.expiry_seconds)
                fields = {}
        if current_instrument is not None:
            fields[current_instrument] = self.redis_tier.encode_order_handles(current_handles)
        written += self.redis_tier.write_fields(key, fields, self.expiry_seconds)
        return written

    def warm_catalogue(self):
        """
        Write the lookup indexes a caller browsing or searching the instruments needs.

        The hashes above answer questions about an instrument whose id or token the caller already has. A caller listing a segment, or searching it for a name, has neither, and would otherwise have to go to unified.instruments. For each segment this writes a catalogue set of every instrument in name, expiry, strike and option type order, and a set of the segment's distinct names; for every instrument it writes the first and last seen dates. The per-segment counts are written last, because their presence is what tells a reader the catalogue for the date is complete.

        Returns:
            int: The number of instruments catalogued.
        """
        seen_key = self.redis_tier.seen_key(self.mapping_date)
        counts = {}
        members = {}
        seen_fields = {}
        pending = 0
        for identity, first_seen_date, last_seen_date in self.postgres_tier.stream_catalogue(self.mapping_date):
            segment = identity["segment"]
            counts[segment] = counts.get(segment, 0) + 1
            catalogue_key = self.redis_tier.catalogue_key(self.mapping_date, segment)
            names_key = self.redis_tier.names_key(self.mapping_date, segment)
            members.setdefault(catalogue_key, []).append(self.redis_tier.encode_catalogue_member(identity))
            members.setdefault(names_key, []).append(self.redis_tier.catalogue_name(identity))
            seen_fields[identity["instrument_id"]] = self.redis_tier.encode_seen(first_seen_date, last_seen_date)
            pending += 1
            if pending >= self.WRITE_BATCH_FIELDS:
                self.redis_tier.write_members(members, self.expiry_seconds)
                self.redis_tier.write_fields(seen_key, seen_fields, self.expiry_seconds)
                members, seen_fields, pending = {}, {}, 0
        self.redis_tier.write_members(members, self.expiry_seconds)
        self.redis_tier.write_fields(seen_key, seen_fields, self.expiry_seconds)
        self.redis_tier.write_fields(self.redis_tier.segments_key(self.mapping_date), counts, self.expiry_seconds)
        return sum(counts.values())

    def clear_other_dates(self):
        """
        Delete every cached mapping date except the one being warmed.

        The dated keys expire on their own at the end of the day, so this exists for the case where a warm is re-run for a corrected date and the superseded date's keys would otherwise still be answerable.

        Returns:
            int: The number of keys deleted.
        """
        return self.redis_tier.clear_other_dates(self.mapping_date)

    def run(self, clear=False):
        """
        Warm every hash for the mapping date and publish the date last.

        Args:
            clear (bool): Whether to delete the cached keys of every other date.

        Returns:
            dict: The counts written, with keys "identities", "tokens", "instruments", "catalogued" and "cleared".

        Raises:
            SystemExit: If Redis cannot be reached.
        """
        if self.redis_tier.connection.client() is None:
            raise SystemExit("redis could not be reached, so the cache was not warmed.")

        started = datetime.datetime.now()
        print(f"warming the instrument mapping cache for {self.mapping_date}")

        identities = self.warm_identities()
        print(f"  identities                {identities:>10}")

        tokens = 0
        for broker in MAPPED_BROKERS:
            written = self.warm_broker_tokens(broker)
            tokens += written
            print(f"  tokens {broker:<18} {written:>10}")

        instruments = self.warm_order_handles()
        print(f"  order handles             {instruments:>10}")

        catalogued = self.warm_catalogue()
        print(f"  catalogue                 {catalogued:>10}")

        cleared = 0
        if clear:
            cleared = self.clear_other_dates()
            print(f"  other dates cleared       {cleared:>10}")

        self.redis_tier.write_current_date(self.mapping_date)
        elapsed = (datetime.datetime.now() - started).total_seconds()
        key = self.redis_tier.current_date_key()
        print(f"published {key} = {self.mapping_date} after {elapsed:.1f} seconds, {identities + tokens + instruments} fields written.")

        return {
            "identities": identities,
            "tokens": tokens,
            "instruments": instruments,
            "catalogued": catalogued,
            "cleared": cleared,
        }


def main():
    """
    Parse the command line arguments and warm the cache.

    Returns:
        dict: The counts written, as described in CacheWarmer.run.
    """
    parser = argparse.ArgumentParser(description="Warm the Redis tier of the instrument mapping cache.")
    parser.add_argument("--date", help="Mapping date to warm, as YYYY-MM-DD. Defaults to the latest mapped date.")
    parser.add_argument("--clear", action="store_true", help="Delete the cached keys of every other date.")
    arguments = parser.parse_args()

    mapping_date = None
    if arguments.date:
        mapping_date = datetime.date.fromisoformat(arguments.date)
    return CacheWarmer(mapping_date).run(arguments.clear)


if __name__ == "__main__":
    main()
