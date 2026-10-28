"""Shares the day's unified instruments out between the brokers' quote websockets.

`unified.broker_quote_capacities` says how many sockets each broker may open and how many instruments each one carries. Every instrument is given to exactly one broker:

1. An instrument whose expiry date is before the mapping date is left out: brokers' masters still list some expired contracts, and no exchange quotes them. On 2026-10-27 that was 277,956 of the 540,627 mapped instruments, 253,795 of them listed by Stoxkart alone.
2. A broker counts as a carrier of an instrument only when it is mapped to it, has capacity, its spelling module can name the instrument, and its own tick normalizer reads that name back to the same token and a segment set holding the instrument's segment. Anything else would stream ticks the unified combiner cannot place.
3. Instruments with fewer carriers go first, so one that only a single broker carries always gets that broker's room before an instrument with alternatives can take it. Within that, securities come before futures and futures before options, and nearer expiries before later ones.
4. Each instrument goes to the carrier with room whose `preference` is lowest, then to the one with the most room left, with ties broken by the broker's name.

Nothing here names a broker or a number: the capacities come from the table and the spellings from the registry.
"""

import datetime
import json

from stock_brokers.instruments.ticks.utilities.registry import NORMALIZERS
from unified_broker_interface.utilities.quote_subscriptions.utilities.registry import (
    QUOTE_SUBSCRIPTION_CLASSES,
)

SUBSCRIPTIONS_KEY = "{broker}:quotes:subscriptions"
PER_SOCKET_KEY = "{broker}:quotes:per_socket"
ALLOCATION_KEY = "unified:quotes:allocation"
MAPPING_META_KEY = "unified:mapping:meta"
MEMBERS_PER_COMMAND = 5000
SHAPE_ORDER = {
    "security": 0,
    "future": 1,
    "option": 2,
}


class QuoteCapacity:
    """What one broker's quote websockets can carry.

    Attributes:
        broker (str): The broker.
        sockets (int): How many quote sockets the broker may open.
        instruments_per_socket (int): How many instruments one socket carries.
        preference (int): The broker's place when an instrument has several carriers; lower is preferred.
        total (int): How many instruments the broker can carry in all.
    """

    def __init__(self, broker, sockets, instruments_per_socket, preference):
        """Records one row of `unified.broker_quote_capacities`.

        Args:
            broker (str): The broker.
            sockets (int): How many quote sockets the broker may open.
            instruments_per_socket (int): How many instruments one socket carries.
            preference (int): The broker's place when an instrument has several carriers; lower is preferred.

        Returns:
            None: This method returns nothing.
        """
        self.broker = broker
        self.sockets = sockets
        self.instruments_per_socket = instruments_per_socket
        self.preference = preference
        self.total = sockets * instruments_per_socket


class QuoteSubscriptionAllocation:
    """One run of the allocation: read the capacities and mappings, choose a broker per instrument, write the sets.

    Attributes:
        connection (psycopg2.extensions.connection): The database connection.
        cache (redis.Redis): The Redis client.
        logger (logging.Logger): Where progress is reported.
        capacities (dict[str, QuoteCapacity]): Each broker with room, by name.
        mapping_date (datetime.date | None): The mapping date allocated.
        assigned (dict[str, list[str]]): Each broker's subscription members.
        uncovered (dict[str, int]): How many instruments no broker could take, by reason.
        instruments (int): How many live instruments the mapping date holds.
        expired (int): How many of the mapping date's instruments had already expired.
    """

    def __init__(self, connection, cache, logger):
        """Prepares a run that has read nothing yet.

        Args:
            connection (psycopg2.extensions.connection): The database connection.
            cache (redis.Redis): The Redis client.
            logger (logging.Logger): Where progress is reported.

        Returns:
            None: This method returns nothing.
        """
        self.connection = connection
        self.cache = cache
        self.logger = logger
        self.capacities = {}
        self.mapping_date = None
        self.assigned = {}
        self.uncovered = {}
        self.instruments = 0
        self.expired = 0

    def read_capacities(self):
        """Reads the brokers that have room from `unified.broker_quote_capacities`.

        Returns:
            dict[str, QuoteCapacity]: Each broker with at least one socket and one instrument per socket.
        """
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT "broker", "sockets", "instruments_per_socket", "preference" FROM unified.broker_quote_capacities ORDER BY "broker"')
            rows = cursor.fetchall()
        capacities = {}
        for broker, sockets, instruments_per_socket, preference in rows:
            capacity = QuoteCapacity(broker, sockets, instruments_per_socket, preference)
            if capacity.total > 0:
                capacities[broker] = capacity
        self.capacities = capacities
        return capacities

    def read_mapping_date(self):
        """The mapping date the Redis cache holds now, which is the one the quote combiner resolves ticks against.

        Returns:
            datetime.date: The mapping date.

        Raises:
            RuntimeError: When `unified:mapping:meta` is missing or has no mapping date.
        """
        meta = json.loads(self.cache.get(MAPPING_META_KEY) or "{}")
        if not meta.get("mapping_date"):
            raise RuntimeError(f"{MAPPING_META_KEY} has no mapping_date; run bin/unified/instruments/map first.")
        return datetime.date.fromisoformat(meta["mapping_date"])

    def read_carriers(self, mapping_date):
        """Reads the date's mappings and keeps, per instrument, each broker that can stream it and its member.

        Args:
            mapping_date (datetime.date): The mapping date.

        Returns:
            dict[str, dict]: Each live instrument id to its sort key (`order`) and its carriers (`members`, broker to member). The expired instruments left out are counted in `expired`.
        """
        spellings = {}
        for spelling_class in QUOTE_SUBSCRIPTION_CLASSES:
            if spelling_class.BROKER_NAME in self.capacities:
                spellings[spelling_class.BROKER_NAME] = spelling_class(self.cache)
        normalizers = {}
        for broker in spellings:
            normalizers[broker] = NORMALIZERS[broker]()
        carriers = {}
        expired = set()
        with self.connection.cursor(name="quote_subscription_mappings") as cursor:
            cursor.itersize = 50000
            cursor.execute(
                """
                SELECT m."instrument_id", m."broker", m."broker_token", m."order_symbol",
                       i."exchange", i."segment", i."shape", i."expiry_date"
                FROM unified.broker_mappings m
                JOIN unified.instruments i USING ("instrument_id")
                WHERE m."mapping_date" = %s
                """,
                (mapping_date,),
            )
            for instrument_id, broker, broker_token, order_symbol, exchange, segment, shape, expiry_date in cursor:
                if expiry_date is not None and expiry_date < mapping_date:
                    expired.add(instrument_id)
                    continue
                instrument = carriers.get(instrument_id)
                if instrument is None:
                    instrument = {
                        "order": (SHAPE_ORDER.get(shape, len(SHAPE_ORDER)), expiry_date or datetime.date.max, instrument_id),
                        "members": {},
                    }
                    carriers[instrument_id] = instrument
                spelling = spellings.get(broker)
                if spelling is None:
                    continue
                identity = {
                    "instrument_id": instrument_id,
                    "exchange": exchange,
                    "segment": segment,
                    "shape": shape,
                }
                member = spelling.member(identity, broker_token, order_symbol)
                if member is None:
                    continue
                if not self._reads_back(normalizers[broker], member, broker_token, order_symbol, segment):
                    continue
                instrument["members"][broker] = member
        self.expired = len(expired)
        return carriers

    def _reads_back(self, normalizer, member, broker_token, order_symbol, segment):
        """Whether the broker's tick normalizer places a member back on the same instrument.

        Args:
            normalizer (TickNormalizer): The broker's tick normalizer.
            member (str): The subscription member.
            broker_token (str): The mapping's broker token.
            order_symbol (str | None): The mapping's order symbol.
            segment (str): The instrument's prefixed segment.

        Returns:
            bool: True when the feed key names the same token or order symbol and its segments hold the instrument's segment.
        """
        key = normalizer.feed_key(normalizer.tick_spelling(member))
        if key is None or segment not in key.segments:
            return False
        if str(key.broker_token) == str(broker_token):
            return True
        return key.order_symbol is not None and key.order_symbol == order_symbol

    def allocate(self, carriers):
        """Gives each instrument to one carrier within the capacities.

        Args:
            carriers (dict[str, dict]): What `read_carriers` returned.

        Returns:
            dict[str, list[str]]: Each broker with room to the members it was given, possibly none.
        """
        remaining = {}
        assigned = {}
        for broker, capacity in self.capacities.items():
            remaining[broker] = capacity.total
            assigned[broker] = []
        uncovered = {
            "no broker can stream it": 0,
            "its only broker is full": 0,
            "all its brokers are full": 0,
        }
        ordered = sorted(carriers.values(), key=self._allocation_order)
        for instrument in ordered:
            members = instrument["members"]
            if not members:
                uncovered["no broker can stream it"] += 1
                continue
            chosen = None
            for broker in sorted(members):
                if remaining[broker] <= 0:
                    continue
                if chosen is None or self._ranks_before(broker, chosen, remaining):
                    chosen = broker
            if chosen is None:
                if len(members) == 1:
                    uncovered["its only broker is full"] += 1
                else:
                    uncovered["all its brokers are full"] += 1
                continue
            remaining[chosen] -= 1
            assigned[chosen].append(members[chosen])
        self.assigned = assigned
        self.uncovered = uncovered
        self.instruments = len(carriers)
        return assigned

    def _ranks_before(self, broker, chosen, remaining):
        """Whether a carrier should take an instrument ahead of the one chosen so far.

        Args:
            broker (str): The carrier being considered.
            chosen (str): The carrier chosen so far.
            remaining (dict[str, int]): Each broker's room left.

        Returns:
            bool: True when the broker's preference is lower, or equal with more room left.
        """
        broker_preference = self.capacities[broker].preference
        chosen_preference = self.capacities[chosen].preference
        if broker_preference != chosen_preference:
            return broker_preference < chosen_preference
        return remaining[broker] > remaining[chosen]

    @staticmethod
    def _allocation_order(instrument):
        """The order instruments are allocated in: fewest carriers first, then the instrument's own sort key.

        Args:
            instrument (dict): One value of what `read_carriers` returned.

        Returns:
            tuple: The sort key.
        """
        return (len(instrument["members"]), instrument["order"])

    def summary(self):
        """What the run decided, as written to `unified:quotes:allocation`.

        Returns:
            dict: The mapping date, the counts covered and uncovered, and each broker's capacity and share.
        """
        brokers = {}
        covered = 0
        for broker, capacity in self.capacities.items():
            members = self.assigned.get(broker, [])
            covered += len(members)
            brokers[broker] = {
                "preference": capacity.preference,
                "sockets": capacity.sockets,
                "instruments_per_socket": capacity.instruments_per_socket,
                "capacity": capacity.total,
                "assigned": len(members),
            }
        return {
            "mapping_date": self.mapping_date.isoformat() if self.mapping_date else None,
            "instruments": self.instruments,
            "expired": self.expired,
            "covered": covered,
            "uncovered": self.uncovered,
            "brokers": brokers,
            "written_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def run(self, mapping_date=None):
        """Reads the capacities and mappings and decides every broker's members, without writing.

        Args:
            mapping_date (datetime.date | None): The mapping date, or None for the one in the Redis mapping cache.

        Returns:
            dict: What `summary` returns.
        """
        self.read_capacities()
        self.mapping_date = mapping_date or self.read_mapping_date()
        self.logger.info(f"Allocating the {self.mapping_date} mapping across {len(self.capacities)} broker(s) with room.")
        carriers = self.read_carriers(self.mapping_date)
        self.allocate(carriers)
        return self.summary()

    def write(self):
        """Replaces each broker's subscription set and per-socket size, and records the summary.

        Each set is built under a staging key and renamed over the live one, so a quote script starting meanwhile reads the old set or the new one, never half of one.

        Returns:
            list[str]: The brokers whose subscription set or per-socket size changed.
        """
        changed = []
        for broker, members in self.assigned.items():
            key = SUBSCRIPTIONS_KEY.format(broker=broker)
            staging_key = f"{key}:staging"
            per_socket = str(self.capacities[broker].instruments_per_socket)
            before = self.cache.smembers(key)
            per_socket_before = self.cache.get(PER_SOCKET_KEY.format(broker=broker))
            pipeline = self.cache.pipeline(transaction=True)
            pipeline.delete(staging_key)
            for start in range(0, len(members), MEMBERS_PER_COMMAND):
                pipeline.sadd(staging_key, *members[start:start + MEMBERS_PER_COMMAND])
            if members:
                pipeline.rename(staging_key, key)
            else:
                pipeline.delete(key)
            pipeline.set(PER_SOCKET_KEY.format(broker=broker), per_socket)
            pipeline.execute()
            if set(members) != before or per_socket_before != per_socket:
                changed.append(broker)
        self.cache.set(ALLOCATION_KEY, json.dumps(self.summary()))
        return changed
