"""Stand-ins for the parts of the order engine's surroundings the offline suites replace: the event log, `uuid.uuid4` and the stop event, and an engine that runs on the route's own thread."""

import datetime
import logging
import uuid

from unified_broker_interface.utilities.order_engine.utilities.engine_lock import (
    EngineLock,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_placement import (
    EnginePlacement,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_runner import (
    OrderEngine,
)
from unified_broker_interface.utilities.order_engine.utilities.intent_handoff import (
    INTENT_STREAM_KEY,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    ParentStore,
)


class RecordingEventLog:
    """Stands in for the event log, keeping every transition in a list instead of a database.

    The engine's recovery reads this back, so the stand-in has to behave like the table in the one way that matters: `read_since` returns rows oldest first within each parent.

    Attributes:
        events (list): Every event recorded, in the order it was written.
        failing_event (int | None): The 1-based write that raises, or None when none does.
        writes (int): How many events have been written.
    """

    def __init__(self):
        """Builds an empty log.

        Returns:
            None: This method returns nothing.
        """
        self.events = []
        self.failing_event = None
        self.writes = 0

    def apply_table(self):
        """Does nothing, since there is no table.

        Returns:
            None: This method returns nothing.
        """

    def record(self, event):
        """Keeps one transition.

        Args:
            event (dict): The event.

        Returns:
            None: This method returns nothing.

        Raises:
            RuntimeError: When this write is the one set to fail.
        """
        self.writes = self.writes + 1
        if self.writes == self.failing_event:
            raise RuntimeError('stand-in event log failure')
        self.events.append(dict(event))

    def record_many(self, events):
        """Keeps several transitions.

        Args:
            events (list): The events.

        Returns:
            None: This method returns nothing.
        """
        for event in events:
            self.record(event)

    def read_since_for_types(self, moment, types):
        """Every transition kept whose order type is one of `types`.

        The real one reads a longer window for the types that outlive a trading day. The stand-in keeps one run's events, so the window means nothing here and only the type filter does.

        Args:
            moment (datetime.datetime): Ignored, since the stand-in keeps only one run's events.
            types (list): The `synthetic_type` values to read.

        Returns:
            list: The matching events, by parent and then sequence.
        """
        wanted = set(types or [])
        return [
            event
            for event in self.read_since(moment)
            if event.get('synthetic_type') in wanted
        ]

    def read_since(self, moment):
        """Every transition kept, ordered as the table orders them.

        Args:
            moment (datetime.datetime): Ignored, since the stand-in keeps only one run's events.

        Returns:
            list: The events, by parent and then sequence.
        """
        del moment
        return sorted(
            self.events,
            key=lambda event: (
                str(event.get('parent_order_id')),
                event.get('sequence') or 0,
            ),
        )

    def shown(self):
        """The events with the values that differ between runs left out.

        Returns:
            list: One dictionary per event, carrying only what a recording can compare.
        """
        shown = []
        for event in self.events:
            kept = {}
            for name, value in event.items():
                if name in ('time', 'engine_instance', 'parent_order_id', 'intent_id'):
                    continue
                if name == 'leg_id' and value:
                    kept[name] = 'leg:' + str(value).rsplit(':', 1)[1]
                    continue
                kept[name] = value
            shown.append(kept)
        return shown



class WindowedEventLog:
    """A stand-in for the synthetic order event table that answers recovery's two time-windowed reads.

    Attributes:
        rows (list): The recorded events, each with an ISO `time` and a `synthetic_type`.
    """

    def __init__(self, rows):
        """Builds the log.

        Args:
            rows (list): The recorded events.

        Returns:
            None: This method returns nothing.
        """
        self.rows = rows

    def read_since(self, moment):
        """Every event at or after a moment.

        Args:
            moment (datetime.datetime): The start of the window.

        Returns:
            list: The events.
        """
        found = []
        for row in self.rows:
            if datetime.datetime.fromisoformat(row['time']) >= moment:
                found.append(row)
        return found

    def read_since_for_types(self, moment, types):
        """Every event of some order types at or after a moment.

        Args:
            moment (datetime.datetime): The start of the window.
            types (list): The order types.

        Returns:
            list: The events.
        """
        found = []
        for row in self.read_since(moment):
            if row['synthetic_type'] in types:
                found.append(row)
        return found

class CountingUuid:
    """A stand-in for `uuid.uuid4` that counts rather than being random.

    Two things in one scenario need different identifiers — two parents, and the tag Groww generates for itself — so replacing `uuid.uuid4` with one constant the way the route suites do is not open here. Counting gives values that are distinct within a scenario and the same on every run, and the count is reset before each scenario so one scenario's numbering does not depend on what ran before it.

    Attributes:
        count (int): How many identifiers have been handed out since the last reset.
    """

    def __init__(self):
        """Builds the counter.

        Returns:
            None: This method returns nothing.
        """
        self.count = 0

    def reset(self):
        """Starts the numbering again, before a scenario.

        Returns:
            None: This method returns nothing.
        """
        self.count = 0

    def __call__(self):
        """The next identifier.

        Returns:
            uuid.UUID: A version 4 identifier whose value is the count.
        """
        self.count = self.count + 1
        return uuid.UUID(int=self.count, version=4)


class OnePassStop:
    """A stop event that lets the engine's loop run a fixed number of passes and then stop.

    The engine blocks on Redis for new entries and runs until it is asked to stop, neither of which suits a recording. This reports "not stopping" for the first few checks and "stopping" afterwards, so `run` makes exactly the passes a scenario needs and returns.

    Attributes:
        remaining (int): How many more checks report that the engine should keep going.
    """

    def __init__(self, passes):
        """Builds the stop event.

        Args:
            passes (int): How many passes of the loop to allow.

        Returns:
            None: This method returns nothing.
        """
        self.remaining = passes

    def is_set(self):
        """Whether the engine should stop, counting down one pass each time it is asked.

        Returns:
            bool: False while passes remain, and True afterwards.
        """
        if self.remaining > 0:
            self.remaining = self.remaining - 1
            return False
        return True

    def set(self):
        """Stops the engine at its next check.

        Returns:
            None: This method returns nothing.
        """
        self.remaining = 0

    def wait(self, seconds):
        """Returns at once instead of waiting, so a backoff costs no time.

        Args:
            seconds (float): Ignored.

        Returns:
            bool: True.
        """
        del seconds
        return True


class InlineEngine:
    """The real order engine, run on the calling thread whenever the route under test waits for an answer.

    The place route writes an intent and waits on its reply list. A suite whose stand-in holds one of these has the stand-in run the engine over every waiting intent at that moment, so the route, the engine and the stubbed brokers run end to end on one thread, in a fixed order, with nothing to wait for. The engine's own Redis round trips are taken back off the stand-in's count, and it can never be the round trip a scenario makes fail, so a recording counts only what the route itself did.

    Attributes:
        fake_redis (redis_stand_ins.InlineEngineRedis): The stand-in the route and the engine share.
        event_log (RecordingEventLog): The engine's record.
        engine (OrderEngine): The engine, with no worker lanes, no gates and no order-update follower, as the place route needs.
        group_ready (bool): Whether the engine's consumer group has been created.
    """

    def __init__(self, fake_redis):
        """Builds the engine over a stand-in, reading the broker selector and exclusions configured now.

        Args:
            fake_redis (redis_stand_ins.InlineEngineRedis): The stand-in the route and the engine share.

        Returns:
            None: This method returns nothing.
        """
        logger = logging.getLogger('test_runs.inline_engine')
        logger.setLevel(logging.CRITICAL)
        self.fake_redis = fake_redis
        self.event_log = RecordingEventLog()
        self.engine = OrderEngine(
            fake_redis,
            EnginePlacement(fake_redis, logger),
            EngineLock(fake_redis, logger),
            logger,
            30.0,
            300,
            self.event_log,
            ParentStore(fake_redis),
        )
        self.group_ready = False

    def place_waiting_intents(self):
        """Places every intent written since the last call, answering each on its reply list.

        Returns:
            None: This method returns nothing.
        """
        round_trips = self.fake_redis.round_trips
        failing_round_trip = self.fake_redis.failing_round_trip
        self.fake_redis.failing_round_trip = None
        try:
            if not self.group_ready:
                self.engine.ensure_group()
                self.group_ready = True
            for stream_key, entry_id, fields in self.engine.read(False):
                if stream_key == INTENT_STREAM_KEY:
                    self.engine.take_intent(entry_id, fields)
        finally:
            self.fake_redis.round_trips = round_trips
            self.fake_redis.failing_round_trip = failing_round_trip
