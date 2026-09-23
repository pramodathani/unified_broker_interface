"""Waking the order types that are watching a price rather than waiting for a fill."""

import json
import time

import redis

from unified_broker_interface.utilities.order_engine.utilities.engine_placement import (
    QUOTES_KEY,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.registry import (
    SYNTHETIC_ORDER_CLASSES,
)

TICK_SECONDS = 1.0


class PriceTicker:
    """Gives every open parent that is watching a price the current quote, about once a second.

    A bracket does nothing until its entry fills, and a scheduled order does nothing until its time comes. A trailing stop is different again: nothing at the broker and nothing on the clock will ever tell it that the market has moved half a rupee in its favour. It has to look.

    Looking is cheap, and that is what makes polling the right answer here rather than a second websocket. Every instrument the whole open set cares about is read in one `HMGET`, which was measured at about a tenth of a millisecond for twenty instruments against a local Redis. Subscribing to the tick feed instead would mean receiving every update for all hundred thousand mapped instruments to use a handful.

    One quote is read per instrument, not per parent, so three trailing stops on the same future cost one field rather than three. Every parent watching that instrument is then handed the same quote, so two parents can never act on two different pictures of the same moment.

    A parent usually watches the instrument it trades, and a few deliberately do not: a cross-instrument conditional exits a Nifty option when the index crosses a level, because the index does not spike the way an illiquid premium does. Such a parent names the second instrument in its `watch_instrument_id` parameter, and both quotes are read and handed over together. That is why a tick carries a dictionary of quotes rather than one quote.

    A parent whose legs span several instruments — a spread, a basket, a strategy being watched for its total profit and loss — gets a quote for every instrument any of its legs trades, read from the legs themselves rather than from a parameter, because they are only known once the legs exist.

    A parent that raises is logged and the rest still get their tick, exactly as on the clock. One order type failing must not strand somebody's trailing stop.

    Attributes:
        cache (redis.Redis): The Redis client, read directly because this is one field read rather than a placement.
        parent_store (ParentStore): The Redis copy of the parents.
        event_log (SyntheticOrderEventLog): The record.
        placement (EnginePlacement): What a type uses to place, cancel or change a leg.
        logger (logging.Logger): The logger.
        gates (RiskGates | None): The limits, including the re-pricing throttle.
        ticked_at (float): When the last tick ran, on the monotonic clock.
        ticks (int): How many ticks have run.
        acted (int): How many times a parent did something on a tick.
        quotes_read (int): How many instrument quotes have been read in total.
    """

    def __init__(self, cache, parent_store, event_log, placement, logger, gates=None):
        """Builds the ticker.

        Args:
            cache (redis.Redis): The Redis client.
            parent_store (ParentStore): The Redis copy of the parents.
            event_log (SyntheticOrderEventLog): The record.
            placement (EnginePlacement): What a type uses to act.
            logger (logging.Logger): The logger.
            gates (RiskGates | None): The limits.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.parent_store = parent_store
        self.event_log = event_log
        self.placement = placement
        self.logger = logger
        self.gates = gates
        self.ticked_at = time.monotonic()
        self.ticks = 0
        self.acted = 0
        self.quotes_read = 0

    def priced_types(self):
        """The names of the order types that want a quote.

        Returns:
            set: The type names.
        """
        wanted = set()
        for name, synthetic_order_class in SYNTHETIC_ORDER_CLASSES.items():
            if getattr(synthetic_order_class, 'WANTS_PRICES', False):
                wanted.add(name)
        return wanted

    def due(self, now=None):
        """Whether enough time has passed for another tick.

        Args:
            now (float | None): The monotonic time, or None for now.

        Returns:
            bool: True when a tick is due.
        """
        now = now if now is not None else time.monotonic()
        return (now - self.ticked_at) >= TICK_SECONDS

    def watching(self, wanted):
        """The open parents of the types that want a quote, with the instruments they watch.

        Args:
            wanted (set): The names of the types that want a quote.

        Returns:
            tuple: A list of parent documents and a sorted list of the instrument ids they name.
        """
        documents = []
        instrument_ids = set()
        for parent_order_id in self.parent_store.open_parent_ids():
            document = self.parent_store.parent(parent_order_id)
            if document is None:
                continue
            if document.get('synthetic_type') not in wanted:
                continue
            watched = self.instruments_of(document)
            if not watched:
                continue
            documents.append(document)
            instrument_ids.update(watched)
        return documents, sorted(instrument_ids)

    def instruments_of(self, document):
        """The instruments one parent wants a quote for.

        Args:
            document (dict): The parent's Redis record.

        Returns:
            list: The instrument ids, the parent's own first.
        """
        watched = []
        instrument_id = document.get('instrument_id')
        if instrument_id:
            watched.append(instrument_id)
        parameters = document.get('parameters') or {}
        other = parameters.get('watch_instrument_id')
        if other and other not in watched:
            watched.append(other)
        for leg in document.get('legs') or []:
            of_leg = leg.get('instrument_id')
            if of_leg and of_leg not in watched:
                watched.append(of_leg)
        return watched

    def quotes(self, instrument_ids):
        """The live quotes for a set of instruments, in one Redis call.

        A quote that is missing or unreadable comes back as None rather than stopping the tick. An instrument whose feed has not started yet is a normal thing on a quiet morning, and a type that needs a price will say so itself.

        Args:
            instrument_ids (list): The instrument ids to read.

        Returns:
            dict: The quote for each instrument id, with None where there was none.
        """
        if not instrument_ids:
            return {}
        try:
            texts = self.cache.hmget(QUOTES_KEY, instrument_ids)
        except redis.RedisError as error:
            self.logger.error(f'The live quotes could not be read: {error}')
            return {}
        self.quotes_read = self.quotes_read + len(instrument_ids)
        found = {}
        for instrument_id, text in zip(instrument_ids, texts):
            if not text:
                found[instrument_id] = None
                continue
            try:
                found[instrument_id] = json.loads(text)
            except (TypeError, ValueError):
                found[instrument_id] = None
        return found

    def tick(self):
        """Gives every open parent of a watching type the current quote.

        Returns:
            int: How many parents did something.
        """
        self.ticked_at = time.monotonic()
        self.ticks = self.ticks + 1
        wanted = self.priced_types()
        if not wanted:
            return 0
        documents, instrument_ids = self.watching(wanted)
        if not documents:
            return 0
        found = self.quotes(instrument_ids)
        acted = 0
        for document in documents:
            quotes = {}
            for instrument_id in self.instruments_of(document):
                quotes[instrument_id] = found.get(instrument_id)
            if self.run_one(document, quotes):
                acted = acted + 1
        self.acted = self.acted + acted
        return acted

    def run_one(self, document, quotes):
        """Gives one parent its quotes.

        Args:
            document (dict): The parent's Redis record.
            quotes (dict): The live quote for each instrument the parent watches, with None where there was none.

        Returns:
            bool: True when the parent did something.
        """
        parent = ParentOrder.from_document(document)
        synthetic_order_class = SYNTHETIC_ORDER_CLASSES.get(
            parent.synthetic_type,
        )
        if synthetic_order_class is None:
            return False
        runner = synthetic_order_class(
            parent,
            self.placement,
            self.event_log,
            self.parent_store,
            self.logger,
            self.gates,
        )
        try:
            return bool(runner.on_price_tick(quotes, time.time()))
        except Exception:
            self.logger.exception(
                f'Parent {parent.parent_order_id} failed on a price tick.'
            )
            return False
