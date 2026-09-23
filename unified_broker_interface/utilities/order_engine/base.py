"""What every synthetic order type shares: starting a parent, recording a leg before sending it, and reading the answer."""

import datetime
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
        parent (ParentOrder): The parent being run.
        placement (EnginePlacement): What reads Redis, chooses a broker and sends.
        event_log (SyntheticOrderEventLog): Where transitions are recorded.
        parent_store (ParentStore): The Redis copy of the parent.
        logger (logging.Logger): The logger.
    """

    SYNTHETIC_TYPE = None
    WANTS_CLOCK = False

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

    def place_leg(self, role, order, started_at, broker_name=None):
        """Records a leg, sends it, records the answer, and returns what the broker said.

        This is the only way an order reaches a broker. The `leg_requested` row is committed before the request is sent, which is what a crash between the two leaves behind, and the rate budget is taken between the two as well, so a leg that waits for a token has already been written down.

        Taking the token after recording and before sending is deliberate. Taking it first would mean an order refused by the budget had no record at all; taking it after sending would not be a limit.

        Args:
            role (str): What the leg is for: `entry`, `stop`, `target`, `slice` or `chase`.
            order (PlaceOrderRequest): The order to send.
            started_at (float): `time.perf_counter()` when the engine took the intent.
            broker_name (str | None): The broker this leg must go to, or None to let the selector choose. Every leg of one parent after the first names the broker the first one chose, because a position split across brokers takes one order per broker to close.

        Returns:
            tuple: The answer's body (dict), its HTTP status (int) and the leg's id (str).

        Raises:
            RefusedRequestError: For an order answered without calling a broker, including one the rate budget would not give a token to.
        """
        prepared = self.placement.prepare(
            order,
            self.parent.instrument_id,
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
            'instrument_id': self.parent.instrument_id,
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
