"""What every synthetic order type shares: starting a parent, recording a leg before sending it, and reading the answer."""

import datetime
import decimal
import time
import uuid

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.place_order_request import (
    PlaceOrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.price_reference import (
    PriceReference,
)
from unified_broker_interface.utilities.order_engine.utilities.quantity_reference import (
    QuantityReference,
)

OUTCOME_LEG_STATES = {
    'accepted': 'acknowledged',
    'rejected': 'rejected',
    'unknown': 'unknown',
}
OUTCOME_PARENT_STATES = {
    'accepted': 'working',
    'rejected': 'rejected',
    'unknown': 'failed',
}


class SyntheticOrder:
    """One parent order being run, whatever kind it is.

    A subclass sets `SYNTHETIC_TYPE` and implements `run`, which is called once with the intent that started it, and may implement `on_leg_update` for a type that reacts to fills. Everything a type shares is here: creating the parent, recording a leg before its request leaves, reading the broker's answer into the parent's state, and keeping Redis in step.

    The order of writes is the point of this class. `record_leg_requested` commits before the request is sent, so a crash between the two leaves a row saying an order may exist at the broker, with the request as it actually went out in `detail`. Nothing else in the engine is allowed to send an order without going through `place_leg`.

    Attributes:
        SYNTHETIC_TYPE (str): The name the caller's `synthetic.type` names this class by.
        WANTS_CLOCK (bool): Whether this type is waiting for a time as well as for a fill, and so wants a tick about once a second.
        WANTS_PRICES (bool): Whether this type is watching the market, and so wants the live quote about once a second.
        parent (ParentOrder): The parent being run.
        placement (EnginePlacement): What reads Redis, chooses a broker and sends.
        event_log (SyntheticOrderEventLog): Where transitions are recorded.
        parent_store (ParentStore): The Redis copy of the parent.
        logger (logging.Logger): The logger.
    """

    SYNTHETIC_TYPE = None
    WANTS_CLOCK = False
    WANTS_PRICES = False

    def __init__(
        self,
        parent,
        placement,
        event_log,
        parent_store,
        logger,
        gates=None,
    ):
        """Builds the runner for one parent.

        Args:
            parent (ParentOrder): The parent being run.
            placement (EnginePlacement): What reads Redis, chooses a broker and sends.
            event_log (SyntheticOrderEventLog): Where transitions are recorded.
            parent_store (ParentStore): The Redis copy of the parent.
            logger (logging.Logger): The logger.
            gates (RiskGates | None): The limits every order passes, or None when there are none.

        Returns:
            None: This method returns nothing.
        """
        self.parent = parent
        self.placement = placement
        self.event_log = event_log
        self.parent_store = parent_store
        self.logger = logger
        self.gates = gates

    @classmethod
    def started(
        cls,
        intent,
        placement,
        event_log,
        parent_store,
        logger,
        gates=None,
    ):
        """Builds the runner and its parent from an intent, without recording anything yet.

        Args:
            intent (dict): The intent document.
            placement (EnginePlacement): What reads Redis, chooses a broker and sends.
            event_log (SyntheticOrderEventLog): Where transitions are recorded.
            parent_store (ParentStore): The Redis copy of the parent.
            logger (logging.Logger): The logger.
            gates (RiskGates | None): The limits every order passes.

        Returns:
            SyntheticOrder: The runner.
        """
        parent = ParentOrder(str(uuid.uuid4()))
        parent.intent_id = intent.get('intent_id')
        parent.synthetic_type = cls.SYNTHETIC_TYPE
        parent.instrument_id = intent.get('instrument_id')
        parent.body = intent.get('body') or {}
        parent.tag = parent.body.get('tag')
        synthetic = parent.body.get('synthetic')
        if isinstance(synthetic, dict):
            parent.parameters = synthetic
        return cls(parent, placement, event_log, parent_store, logger, gates)

    def run(self, intent, started_at):
        """Runs the parent from its intent and answers the waiting API worker.

        Args:
            intent (dict): The intent document.
            started_at (float | None): `time.perf_counter()` when the engine took the intent, or None for a leg placed in reaction to a fill, which nobody is waiting on.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            NotImplementedError: Always, in this class.
        """
        raise NotImplementedError(
            f'{type(self).__name__} does not implement run'
        )

    def read_order(self, body):
        """Rebuilds the validated order from the caller's body, exactly as the route built it.

        Args:
            body (dict | None): The caller's decoded JSON body.

        Returns:
            PlaceOrderRequest: The validated order.

        Raises:
            RefusedRequestError: With HTTP 400 when the body does not validate, which means the route and the engine disagree and is worth answering rather than hiding.
        """
        try:
            return PlaceOrderRequest(body)
        except InvalidOrderError as error:
            raise RefusedRequestError.refusal(str(error), 400)

    def concrete_order(self, order):
        """Replaces any price or quantity reference with the number it works out to.

        The result is an ordinary order, built by `PlaceOrderRequest` from an ordinary body, so every check a caller's own numbers face — the lot size, the tick size, the contract size, whether a priced order carries a price — applies to a number the engine worked out too. A reference is a way of saying which number, not a way around the checks.

        Args:
            order (PlaceOrderRequest): The validated order, which may carry references.

        Returns:
            PlaceOrderRequest: The order with real numbers, or the same order when it carried no references.

        Raises:
            RefusedRequestError: With HTTP 503 when the quote or the positions are missing, 409 when there is no position to close, and 400 when the price works out at zero or below.
        """
        price_reference = getattr(order, 'price_reference', None)
        quantity_reference = getattr(order, 'quantity_reference', None)
        if price_reference is None and quantity_reference is None:
            return order

        instrument, quote, positions = self.placement.market_context(
            self.parent.instrument_id,
            price_reference is not None,
            quantity_reference is not None,
        )
        body = dict(self.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)

        transaction_type = order.transaction_type
        if quantity_reference is not None:
            quantity, transaction_type = QuantityReference().resolve(
                quantity_reference,
                positions,
                self.parent.instrument_id,
                transaction_type,
                order.quantity,
            )
            body['quantity'] = quantity
            body['transaction_type'] = transaction_type
        if price_reference is not None:
            tick_size = order.agreed_tick_size(instrument.handles)
            if tick_size is None:
                raise RefusedRequestError.refusal(
                    'a price reference needs a tick size the brokers agree on '
                    'and there is none for this instrument',
                    503,
                    instrument_id=self.parent.instrument_id,
                )
            price = PriceReference(order).resolve(
                price_reference,
                quote,
                transaction_type,
                tick_size,
            )
            body['price'] = str(price)
        return self.read_order(body)

    def on_leg_update(self, leg, changes):
        """Reacts to one of this parent's legs changing at a broker.

        A type that does nothing after its order is placed leaves this alone. A bracket arms its stop and its target here; an OCO reduces the sibling of whatever just filled. Whatever it does, it must leave the parent consistent, because the update that follows may arrive before it has finished.

        Args:
            leg (OrderLeg): The leg the update was about, already changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """

    def on_clock_tick(self, now):
        """Acts on the time having passed, for a type that is waiting for one.

        Only types that set `WANTS_CLOCK` are given this, and only while their parent is open. A type waiting for a fill leaves it alone.

        Args:
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the parent did something, which is only used for the engine's counters.
        """
        return False

    def on_price_tick(self, quotes, now):
        """Acts on where the market is, for a type that is watching it.

        Only types that set `WANTS_PRICES` are given this, and only while their parent is open. A quote is the instrument's whole entry in `unified:quotes:live`, read once for every parent watching that instrument, so two parents can never act on two different pictures of the same moment.

        It is a dictionary rather than one quote because a few types deliberately watch something other than what they trade: a cross-instrument conditional exits an option when the index moves. Most types want `own_quote` and nothing else.

        A quote is None when the feed has not carried that instrument yet, which is normal early in the morning and after a feed restart. A type that cannot act without a price returns False and waits for the next tick rather than guessing.

        Args:
            quotes (dict): The live quote for each instrument this parent watches, with None where there was none.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the parent did something, which is only used for the engine's counters.
        """
        return False

    def remember_tick_size(self, order):
        """Works this instrument's tick size out once, and keeps it on the parent.

        A type that watches the market needs the tick size on every tick, to snap a price it computed onto a boundary the exchange will accept. Reading it from the catalogue each time would put a Redis round trip inside the tick, once per parent per second, to fetch a number that cannot change while the parent is open.

        So it is resolved when the parent is created, where a round trip is already being made, and kept as text in the parent's parameters. Text rather than a float, for the same reason the catalogue stores it as text: a tick size of 0.05 is not representable in binary floating point, and a price built from a tick size that is slightly wrong is off-tick and refused.

        Args:
            order (PlaceOrderRequest): The validated order, which carries the agreement rule.

        Returns:
            decimal.Decimal: The tick size.

        Raises:
            RefusedRequestError: With HTTP 503 when the brokers do not agree on a tick size for this instrument, since a type that computes prices cannot run without one.
        """
        instrument, _, _ = self.placement.market_context(
            self.parent.instrument_id,
            False,
            False,
        )
        tick_size = order.agreed_tick_size(instrument.handles)
        if tick_size is None:
            raise RefusedRequestError.refusal(
                'this order type works its prices out from the live quote, '
                'which needs a tick size the brokers agree on, and there is '
                'none for this instrument',
                503,
                instrument_id=self.parent.instrument_id,
            )
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['tick_size'] = str(tick_size)
        return tick_size

    def tick_size(self):
        """The tick size `remember_tick_size` kept, read back as a number.

        Returns:
            decimal.Decimal | None: The tick size, or None when the parent has none.
        """
        text = self.parent.parameters.get('tick_size')
        if not text:
            return None
        try:
            return decimal.Decimal(str(text))
        except decimal.InvalidOperation:
            return None

    def view(self, quotes, instrument_id=None):
        """The market, as this parent's instrument's quote and tick size show it.

        Args:
            quotes (dict): The quotes the tick carried.
            instrument_id (str | None): The instrument to look at, or None for this parent's own.

        Returns:
            MarketView: The reader, which answers None for everything when there is no quote.
        """
        wanted = instrument_id or self.parent.instrument_id
        return MarketView(quotes.get(wanted), self.tick_size())

    def chosen_broker(self):
        """The broker this parent's legs go to, once one of them has picked one.

        Every leg of one parent has to go to the same broker. A stop at one broker cannot protect a position held at another: the two accounts know nothing about each other, so the stop would open a fresh short at the second broker while the position sat unprotected at the first. Where a type places legs at different moments — a backstop now and an exit an hour later — the later ones have to be told where the earlier ones went, because the round robin will otherwise have moved on.

        Returns:
            str | None: The broker name, or None when nothing has been placed yet and the selector is free to choose.
        """
        for leg in self.parent.legs:
            if leg.broker:
                return leg.broker
        return None

    def own_quote(self, quotes):
        """This parent's own instrument's quote, out of the ones a tick carried.

        Args:
            quotes (dict): The quotes the tick carried.

        Returns:
            dict | None: The quote, or None when the feed has not carried this instrument.
        """
        return quotes.get(self.parent.instrument_id)

    def cancel_leg(self, leg, reason):
        """Cancels one leg at its broker and records both the asking and the answer.

        A cancel is recorded as asked before it is sent, for the same reason a placement is: the engine has to be able to tell, after a crash, that it had begun.

        Args:
            leg (OrderLeg): The leg to cancel.
            reason (str): Why, for a person reading the parent later.

        Returns:
            bool: True when the broker accepted the cancel.
        """
        self.record({
            'event': 'leg_cancel_requested',
            'parent_state': self.parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
            'leg_state': leg.state,
            'broker': leg.broker,
            'broker_order_id': leg.broker_order_id,
            'status_message': reason,
        })
        if not self.take_rate_token(leg, reason):
            return False
        try:
            answer = self.placement.cancel(leg.broker, leg.broker_order_id)
        except Exception as error:
            self.record({
                'event': 'leg_cancelled',
                'parent_state': self.parent.state,
                'leg_id': leg.leg_id,
                'leg_role': leg.role,
                'leg_state': leg.state,
                'broker': leg.broker,
                'broker_order_id': leg.broker_order_id,
                'outcome': 'unknown',
                'status_message': f'the cancel could not be sent: {error}',
            })
            return False
        self.record({
            'event': 'leg_cancelled',
            'parent_state': self.parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
            # The broker's own order update decides when the leg is really cancelled. An accepted
            # cancel is a promise, not a fact, and treating it as one is how an order that went on
            # to fill anyway gets forgotten about.
            'leg_state': leg.state,
            'broker': leg.broker,
            'broker_order_id': leg.broker_order_id,
            'outcome': answer.outcome,
            'status_message': answer.status_message,
            'detail': {
                'broker_response': answer.response_body,
            },
        })
        return answer.outcome == 'accepted'

    def reduce_leg(self, leg, quantity, reason):
        """Reduces one leg's quantity at its broker, rather than cancelling and replacing it.

        This is the Atlas's rule for every linked pair: when one leg fills, reduce the other by what filled instead of cancelling it. Cancelling leaves a window with nothing protecting the position, and replacing loses the order's place in the queue.

        Args:
            leg (OrderLeg): The leg to reduce.
            quantity (int): The new quantity, in the broker's own terms.
            reason (str): Why, for a person reading the parent later.

        Returns:
            bool: True when the broker accepted the change.
        """
        if quantity < 1:
            return self.cancel_leg(leg, reason)
        if not self.take_rate_token(leg, reason):
            return False
        try:
            answer = self.placement.modify_leg(
                leg.broker,
                leg.broker_order_id,
                quantity=quantity,
            )
        except Exception as error:
            self.record({
                'event': 'leg_update',
                'parent_state': self.parent.state,
                'leg_id': leg.leg_id,
                'leg_role': leg.role,
                'broker': leg.broker,
                'broker_order_id': leg.broker_order_id,
                'outcome': 'unknown',
                'status_message': (
                    f'{reason}; the change could not be sent: {error}'
                ),
            })
            return False
        accepted = answer.outcome == 'accepted'
        self.record({
            'event': 'leg_update',
            'parent_state': self.parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
            'broker': leg.broker,
            'broker_order_id': leg.broker_order_id,
            'quantity': quantity if accepted else leg.quantity,
            'outcome': answer.outcome,
            'status_message': f'{reason}; {answer.status_message or "accepted"}',
            'detail': {
                'broker_response': answer.response_body,
            },
        })
        return accepted

    def reprice_leg(self, leg, price, trigger_price, reason):
        """Moves one leg's prices at its broker, leaving its quantity alone.

        Moving a stop to breakeven after a first target fills works through this, and so will every type that re-prices a resting order.

        Args:
            leg (OrderLeg): The leg to move.
            price (decimal.Decimal | None): The new limit price, or None to leave it.
            trigger_price (decimal.Decimal | None): The new trigger price, or None to leave it.
            reason (str): Why, for a person reading the parent later.

        Returns:
            bool: True when the broker accepted the change.
        """
        if not self.moves_the_price(leg, price, trigger_price):
            return False
        if not self.allowed_to_reprice(leg, reason):
            return False
        if not self.take_rate_token(leg, reason):
            return False
        try:
            answer = self.placement.modify_leg(
                leg.broker,
                leg.broker_order_id,
                price=price,
                trigger_price=trigger_price,
            )
        except Exception as error:
            self.record({
                'event': 'leg_update',
                'parent_state': self.parent.state,
                'leg_id': leg.leg_id,
                'leg_role': leg.role,
                'broker': leg.broker,
                'broker_order_id': leg.broker_order_id,
                'outcome': 'unknown',
                'status_message': (
                    f'{reason}; the move could not be sent: {error}'
                ),
            })
            return False
        accepted = answer.outcome == 'accepted'
        if accepted and self.gates is not None:
            self.gates.record_reprice(leg.leg_id)
        self.record({
            'event': 'leg_update',
            'parent_state': self.parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
            'broker': leg.broker,
            'broker_order_id': leg.broker_order_id,
            'price': self.json_number(price) if accepted else leg.price,
            'trigger_price': (
                self.json_number(trigger_price)
                if accepted
                else leg.trigger_price
            ),
            'outcome': answer.outcome,
            'status_message': f'{reason}; {answer.status_message or "accepted"}',
            'detail': {
                'broker_response': answer.response_body,
            },
        })
        return accepted

    def moves_the_price(self, leg, price, trigger_price):
        """Whether a change would actually move this leg, or would send the prices it already has.

        A type that works out where its order should be and asks for that on every tick will most of the time ask for exactly where the order already is, because the market has not moved. Sending that is a request an exchange counts, a broker charges for and a ratio remembers, in exchange for nothing at all.

        This is not a configured limit and there is nothing to tune. Moving an order to where it already is is never what the caller meant, so it is refused wherever it comes from, and nothing is recorded either: nothing happened, and a log full of moves that moved nothing would bury the ones that did.

        Args:
            leg (OrderLeg): The leg being moved.
            price (decimal.Decimal | None): The new limit price, or None to leave it.
            trigger_price (decimal.Decimal | None): The new trigger price, or None to leave it.

        Returns:
            bool: True when at least one of the two prices differs from what the leg carries.
        """
        if price is not None and self.json_number(price) != leg.price:
            return True
        if (
            trigger_price is not None
            and self.json_number(trigger_price) != leg.trigger_price
        ):
            return True
        return False

    def allowed_to_reprice(self, leg, reason):
        """Whether this leg has been left alone long enough to be moved again.

        A type following the market has no limit of its own, so the throttle gives it one. A refusal is recorded against the leg, because unlike a move that would change nothing this one is a move the type did want and did not get, and somebody reading the parent back needs to see that the order stayed where it was on purpose.

        Args:
            leg (OrderLeg): The leg being moved.
            reason (str): What the move was for, for the message.

        Returns:
            bool: True when the move may be sent.
        """
        if self.gates is None:
            return True
        if self.gates.allow_reprice(leg.leg_id):
            return True
        self.record({
            'event': 'leg_update',
            'parent_state': self.parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
            'broker': leg.broker,
            'broker_order_id': leg.broker_order_id,
            'outcome': 'rejected',
            'status_message': (
                f'{reason}; not sent: this order was moved less than '
                f'{self.gates.throttle.minimum_seconds} seconds ago'
            ),
        })
        return False

    def take_rate_token(self, leg, reason):
        """Waits for the rate budget to allow one more request to this leg's broker.

        Placing, changing and cancelling all count the same to an exchange, so all three pass through here. Until this existed the budget covered placements only, which was tolerable while nothing changed an order much and stops being tolerable the moment a type re-prices: a chaser walking towards the touch spends its whole budget on changes and would have been invisible to a limit that only watched placements.

        A refusal is recorded against the leg and returns False rather than raising, because the caller is usually reacting to a fill and has other legs to attend to. The thing that did not happen is in the log either way.

        Args:
            leg (OrderLeg): The leg the request is about.
            reason (str): What the request was for, for the message.

        Returns:
            bool: True when the request may be sent.
        """
        if self.gates is None:
            return True
        try:
            self.gates.take_rate_token(leg.broker)
        except RefusedRequestError as refusal:
            self.record({
                'event': 'leg_update',
                'parent_state': self.parent.state,
                'leg_id': leg.leg_id,
                'leg_role': leg.role,
                'broker': leg.broker,
                'broker_order_id': leg.broker_order_id,
                'outcome': 'rejected',
                'status_message': (
                    f'{reason}; not sent: {refusal.body.get("error")}'
                ),
            })
            return False
        return True

    def json_number(self, value):
        """A price as a number the parent's Redis record can hold.

        `PlaceOrderRequest` keeps prices as `decimal.Decimal`, which is right for comparing them against a tick size and wrong for `json.dumps`, which refuses one outright. The parent record is written to Redis as JSON after every transition, so a Decimal reaching a leg would stop a limit order being saved at all — and every order the engine had placed until now happened to be a market order, so nothing noticed.

        A price rounded to four decimal places, which is what `NUMERIC(18,4)` stores and what every other price in this system is, survives a float exactly.

        Args:
            value (decimal.Decimal | int | float | None): The price.

        Returns:
            float | None: The price as a float, or None.
        """
        if value is None:
            return None
        return float(value)

    def now(self):
        """The moment a transition is being recorded at.

        Returns:
            datetime.datetime: Now, in UTC.
        """
        return datetime.datetime.now(datetime.timezone.utc)

    def record(self, event):
        """Writes one transition, commits it and applies it to the parent.

        Recording and applying are one step so that the parent in memory can never be ahead of the record on disk. If the write fails the parent is left as it was, and the caller decides what that means.

        Args:
            event (dict): The event's columns, without `parent_order_id`, `sequence` or `time`.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Anything the database raises.
        """
        recorded = dict(event)
        recorded['parent_order_id'] = self.parent.parent_order_id
        recorded['sequence'] = self.parent.next_sequence()
        recorded['time'] = self.now()
        recorded.setdefault('synthetic_type', self.parent.synthetic_type)
        recorded.setdefault('intent_id', self.parent.intent_id)
        self.event_log.record(recorded)
        self.parent.apply_event(recorded)

    def record_received(self):
        """Records that the parent exists, with the caller's body kept for a later leg to be built from.

        Returns:
            None: This method returns nothing.
        """
        self.record({
            'event': 'parent_received',
            'parent_state': 'received',
            'instrument_id': self.parent.instrument_id,
            'detail': {
                'body': self.parent.body,
                'parameters': self.parent.parameters,
            },
        })

    def record_state(self, state, status_message=None):
        """Records a change of the parent's own state.

        Args:
            state (str): The state moved to.
            status_message (str | None): Why, for a state a person will have to read.

        Returns:
            None: This method returns nothing.
        """
        self.record({
            'event': 'parent_state_changed',
            'parent_state': state,
            'status_message': status_message,
        })

    def abandon(self, status_message):
        """Closes a parent that was recorded and then refused before anything reached a broker.

        Without this a refusal raised after `record_received` would leave the parent in `received` for ever: not terminal, so the open set keeps it, and recovery picks it up at every restart with nothing it can do about it. A refusal means no request was sent, so `rejected` is the honest end.

        A parent with nothing recorded yet, such as a dry run's, is left alone, because there is nothing to close.

        Args:
            status_message (str | None): Why the order was refused.

        Returns:
            None: This method returns nothing.
        """
        if self.parent.sequence < 1 or self.parent.is_terminal():
            return
        try:
            self.record_state('rejected', status_message)
            self.save()
        except Exception:
            self.logger.exception(
                f'Parent {self.parent.parent_order_id} was refused but could '
                'not be closed, so recovery will find it open.'
            )

    def place_leg(
        self,
        role,
        order,
        started_at,
        broker_name=None,
        instrument_id=None,
    ):
        """Records a leg, sends it, records the answer, and returns what the broker said.

        This is the only way an order reaches a broker. The `leg_requested` row is committed before the request is sent, which is what a crash between the two leaves behind, and the rate budget is taken between the two as well, so a leg that waits for a token has already been written down.

        Taking the token after recording and before sending is deliberate. Taking it first would mean an order refused by the budget had no record at all; taking it after sending would not be a limit.

        Args:
            role (str): What the leg is for: `entry`, `stop`, `target`, `slice` or `chase`.
            order (PlaceOrderRequest): The order to send.
            started_at (float): `time.perf_counter()` when the engine took the intent.
            broker_name (str | None): The broker this leg must go to, or None to let the selector choose. Every leg of one parent after the first names the broker the first one chose, because a position split across brokers takes one order per broker to close.
            instrument_id (str | None): The instrument this leg trades, or None for the parent's own. Only the types whose legs span several instruments — a spread, a basket, a hedge — pass this.

        Returns:
            tuple: The answer's body (dict), its HTTP status (int) and the leg's id (str).

        Raises:
            RefusedRequestError: For an order answered without calling a broker, including one the rate budget would not give a token to.
        """
        instrument_id = instrument_id or self.parent.instrument_id
        prepared = self.placement.prepare(
            order,
            instrument_id,
            broker_name,
        )
        if started_at is None:
            # A leg placed in reaction to a fill has no request waiting on it, so there is no
            # arrival to measure from. Measuring from here reports the engine's own work on this
            # leg, which is the only span that means anything.
            started_at = time.perf_counter()
        leg_id = self.parent.next_leg_id()
        broker_request = prepared.broker_request
        self.record({
            'event': 'leg_requested',
            'parent_state': self.parent.state,
            'leg_id': leg_id,
            'leg_role': role,
            'leg_state': 'sending',
            'broker': prepared.broker_name,
            'tag_sent': broker_request.tag,
            'identifier_sent': prepared.identifier_sent,
            'instrument_id': instrument_id,
            'transaction_type': order.transaction_type,
            'product': order.product,
            'order_type': order.order_type,
            'validity': order.validity,
            'quantity': order.quantity,
            'price': self.json_number(order.price),
            'trigger_price': self.json_number(order.trigger_price),
            'detail': {
                'request': broker_request.shown(),
            },
        })

        if self.gates is not None:
            self.gates.take_rate_token(prepared.broker_name)
        body, status = self.placement.send(prepared, started_at)
        if self.gates is not None:
            self.gates.count_sent(prepared.broker_name)
        outcome = body.get('outcome')
        self.record({
            'event': 'leg_answered',
            'parent_state': self.parent.state,
            'leg_id': leg_id,
            'leg_role': role,
            'leg_state': OUTCOME_LEG_STATES.get(outcome, 'unknown'),
            'broker': prepared.broker_name,
            'broker_order_id': body.get('order_id'),
            'outcome': outcome,
            'status_message': body.get('status_message'),
            'detail': {
                'broker_response': body.get('broker_response'),
            },
        })
        return body, status, leg_id

    def save(self):
        """Writes the parent to Redis, which is a cache and may fail without changing an answer.

        Returns:
            None: This method returns nothing.
        """
        try:
            self.parent_store.save(self.parent)
        except Exception:
            self.logger.exception(
                f'The Redis copy of parent {self.parent.parent_order_id} '
                'could not be written; the event log still has it.'
            )
