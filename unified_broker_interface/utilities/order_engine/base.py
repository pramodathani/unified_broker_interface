"""What every synthetic order type shares: starting a parent, recording a leg before sending it, and reading the answer."""

import datetime
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
        parent (ParentOrder): The parent being run.
        placement (EnginePlacement): What reads Redis, chooses a broker and sends.
        event_log (SyntheticOrderEventLog): Where transitions are recorded.
        parent_store (ParentStore): The Redis copy of the parent.
        logger (logging.Logger): The logger.
    """

    SYNTHETIC_TYPE = None

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
            started_at (float): `time.perf_counter()` when the engine took the intent.

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

    def place_leg(self, role, order, started_at):
        """Records a leg, sends it, records the answer, and returns what the broker said.

        This is the only way an order reaches a broker. The `leg_requested` row is committed before the request is sent, which is what a crash between the two leaves behind, and the rate budget is taken between the two as well, so a leg that waits for a token has already been written down.

        Taking the token after recording and before sending is deliberate. Taking it first would mean an order refused by the budget had no record at all; taking it after sending would not be a limit.

        Args:
            role (str): What the leg is for: `entry`, `stop`, `target`, `slice` or `chase`.
            order (PlaceOrderRequest): The order to send.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict), its HTTP status (int) and the leg's id (str).

        Raises:
            RefusedRequestError: For an order answered without calling a broker, including one the rate budget would not give a token to.
        """
        prepared = self.placement.prepare(order, self.parent.instrument_id)
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
            'price': order.price,
            'trigger_price': order.trigger_price,
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
