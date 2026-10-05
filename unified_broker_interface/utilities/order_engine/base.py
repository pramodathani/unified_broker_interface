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
from unified_broker_interface.utilities.order_engine.utilities.reduce_only import (
    ReduceOnlyCheck,
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
    """One parent order being run: a `simple` order or a `plan`, the two kinds the engine runs.

    A subclass sets `SYNTHETIC_TYPE` and implements `run`, which is called once with the intent that started it, and may implement `on_leg_update` for a type that reacts to fills. Everything a type shares is here: creating the parent, recording a leg before its request leaves, reading the broker's answer into the parent's state, and keeping Redis in step.

    The order of writes is the point of this class. `record_leg_requested` commits before the request is sent, so a crash between the two leaves a row saying an order may exist at the broker, with the request as it actually went out in `detail`. Nothing else in the engine is allowed to send an order without going through `place_leg`.

    Attributes:
        SYNTHETIC_TYPE (str): The name the caller's `synthetic.type` names this class by.
        WANTS_CLOCK (bool): Whether this type is waiting for a time as well as for a fill, and so wants a tick about once a second.
        WANTS_PRICES (bool): Whether this type is watching the market, and so wants the live quote about once a second.
        FINISHES_WITH_LEGS (bool): Whether the parent is done once every leg has finished, for a type that places everything at once and does nothing afterwards.
        CARRIES_OVERNIGHT (bool): Whether a parent of this type outlives the trading day, so that recovery reads its events from further back than this morning.
        parent (ParentOrder): The parent being run.
        placement (EnginePlacement): What reads Redis, chooses a broker and sends.
        event_log (SyntheticOrderEventLog): Where transitions are recorded.
        parent_store (ParentStore): The Redis copy of the parent.
        logger (logging.Logger): The logger.
    """

    SYNTHETIC_TYPE = None
    WANTS_CLOCK = False
    WANTS_PRICES = False
    FINISHES_WITH_LEGS = False
    CARRIES_OVERNIGHT = False

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

        It is a dictionary rather than one quote because a few types deliberately watch something other than what they trade: a plan's order may watch the index while it trades an option.

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

    def cancel_leg(self, leg, reason):
        """Cancels one leg at its broker and records both the asking and the answer.

        A cancel is recorded as asked before it is sent, for the same reason a placement is: the engine has to be able to tell, after a crash, that it had begun.

        Args:
            leg (OrderLeg): The leg to cancel.
            reason (str): Why, for a person reading the parent later.

        Returns:
            bool: True when the broker accepted the cancel.
        """
        outcome, _, _ = self.cancel_leg_answered(leg, reason)
        return outcome == 'accepted'

    def cancel_leg_answered(self, leg, reason):
        """Cancels one leg at its broker, records both the asking and the answer, and says what the broker answered.

        Args:
            leg (OrderLeg): The leg to cancel.
            reason (str): Why, for a person reading the parent later.

        Returns:
            tuple: The outcome (str: `accepted`, `rejected` or `unknown`), the status message (str or None) and the broker's response (object or None).
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
            return 'rejected', 'the order rate budget is full, so the cancel was not sent', None
        try:
            answer = self.placement.cancel(leg.broker, leg.broker_order_id)
        except RefusedRequestError as refusal:
            status_message = f"the cancel was not sent: {refusal.body.get('error')}"
            self.record({
                'event': 'leg_cancelled',
                'parent_state': self.parent.state,
                'leg_id': leg.leg_id,
                'leg_role': leg.role,
                'leg_state': leg.state,
                'broker': leg.broker,
                'broker_order_id': leg.broker_order_id,
                'outcome': 'rejected',
                'status_message': status_message,
            })
            return 'rejected', status_message, None
        except Exception as error:
            status_message = f'the cancel could not be sent: {error}'
            self.record({
                'event': 'leg_cancelled',
                'parent_state': self.parent.state,
                'leg_id': leg.leg_id,
                'leg_role': leg.role,
                'leg_state': leg.state,
                'broker': leg.broker,
                'broker_order_id': leg.broker_order_id,
                'outcome': 'unknown',
                'status_message': status_message,
            })
            return 'unknown', status_message, None
        self.record({
            'event': 'leg_cancelled',
            'parent_state': self.parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
            'leg_state': leg.state,
            'broker': leg.broker,
            'broker_order_id': leg.broker_order_id,
            'outcome': answer.outcome,
            'status_message': answer.status_message,
            'detail': {
                'broker_response': answer.response_body,
            },
        })
        return answer.outcome, answer.status_message, answer.response_body

    def trading_segment(self):
        """The exchange-prefixed segment of this parent's instrument, which decides the calendar its times follow.

        Returns:
            str: The segment, such as `nse_equities`, or an empty string when the instrument has none.
        """
        instrument, _, _ = self.placement.market_context(
            self.parent.instrument_id,
            False,
            False,
        )
        return instrument.segment

    def modify_held(self, price, quantity, dry_run):
        """Changes an order the engine is still holding, which only a type that holds orders can do.

        Args:
            price (decimal.Decimal | None): The new limit price, or None to keep it.
            quantity (int | None): The new quantity in units, or None to keep it.
            dry_run (bool): Whether to check the change without making it.

        Returns:
            tuple: Never returns in this class.

        Raises:
            RefusedRequestError: With HTTP 409, always, because this type holds no order of its own; its legs are changed by broker and order_id.
        """
        raise RefusedRequestError.refusal(
            f'a {self.parent.synthetic_type} order holds no order of its own '
            'to change; change its legs with broker and order_id',
            409,
            parent_id=self.parent.parent_order_id,
        )

    def modify_part(self, path, price, trigger_price, quantity, dry_run):
        """Changes one part of a plan before it is sent, which only a plan has.

        Args:
            path (str): The part's path.
            price (decimal.Decimal | None): The new limit price, or None to keep it.
            trigger_price (decimal.Decimal | None): The new trigger price, or None to keep it.
            quantity (int | None): The new quantity in units, or None to keep it.
            dry_run (bool): Whether to check the change without making it.

        Returns:
            tuple: Never returns in this class.

        Raises:
            RefusedRequestError: With HTTP 409, always, because only a plan order has parts.
        """
        del price, trigger_price, quantity, dry_run
        raise RefusedRequestError.refusal(
            f'a {self.parent.synthetic_type} order has no parts, so part {path} cannot be changed; only a plan order has parts',
            409,
            parent_id=self.parent.parent_order_id,
        )

    def cancel_part(self, path, dry_run):
        """Cancels one part of a plan, which only a plan has.

        Args:
            path (str): The part's path.
            dry_run (bool): Whether to check the cancel without making it.

        Returns:
            tuple: Never returns in this class.

        Raises:
            RefusedRequestError: With HTTP 409, always, because only a plan order has parts.
        """
        del dry_run
        raise RefusedRequestError.refusal(
            f'a {self.parent.synthetic_type} order has no parts, so part {path} cannot be cancelled; only a plan order has parts',
            409,
            parent_id=self.parent.parent_order_id,
        )

    def apply_outside_modification(
        self,
        leg,
        quantity,
        price,
        trigger_price,
        quantity_units=None,
    ):
        """Sends a change the caller asked for through `PUT /api/orders/modify` to one of this parent's legs, records it, and lets the type carry on from the new values.

        The change is recorded as a `leg_update`, the event a type's own repricing and reducing already write, so recovery replays it and the leg keeps the caller's price and quantity after a restart. The re-pricing throttle, the day's order cap and the rate budget apply to it as they do to the type's own changes. When the broker accepts it, `on_leg_modified` is called with what the leg held before.

        Args:
            leg (OrderLeg): The leg to change.
            quantity (int | None): The new quantity, in the broker's own terms, which is what is sent, or None to leave it.
            price (decimal.Decimal | None): The new limit price, or None to leave it.
            trigger_price (decimal.Decimal | None): The new trigger price, or None to leave it.
            quantity_units (int | None): The new quantity as the caller gave it, which is how a leg records its quantity; None records `quantity` instead.

        Returns:
            tuple: The outcome (str: `accepted`, `rejected` or `unknown`), the status message (str or None) and the broker's response (object or None).
        """
        reason = 'changed through PUT /api/orders/modify'
        before = {
            'quantity': leg.quantity,
            'price': leg.price,
            'trigger_price': leg.trigger_price,
        }
        moves_price = price is not None or trigger_price is not None
        if moves_price and not self.allowed_to_reprice(leg, reason):
            return 'rejected', 'this order was moved too recently to move again yet', None
        if not self.has_room_today(leg, reason):
            return 'rejected', "the broker's daily order cap has no room for this change", None
        if not self.take_rate_token(leg, reason):
            return 'rejected', 'the order rate budget is full, so the change was not sent', None
        try:
            answer = self.placement.modify_leg(
                leg.broker,
                leg.broker_order_id,
                quantity=quantity,
                price=price,
                trigger_price=trigger_price,
            )
        except Exception as error:
            status_message = f'{reason}; the change could not be sent: {error}'
            self.record({
                'event': 'leg_update',
                'parent_state': self.parent.state,
                'leg_id': leg.leg_id,
                'leg_role': leg.role,
                'broker': leg.broker,
                'broker_order_id': leg.broker_order_id,
                'outcome': 'unknown',
                'status_message': status_message,
            })
            return 'unknown', status_message, None
        accepted = answer.outcome == 'accepted'
        if accepted and moves_price and self.gates is not None:
            self.gates.record_reprice(leg.leg_id)
        event = {
            'event': 'leg_update',
            'parent_state': self.parent.state,
            'leg_id': leg.leg_id,
            'leg_role': leg.role,
            'broker': leg.broker,
            'broker_order_id': leg.broker_order_id,
            'outcome': answer.outcome,
            'status_message': f'{reason}; {answer.status_message or answer.outcome}',
            'detail': {
                'broker_response': answer.response_body,
                'changed_by': 'caller',
            },
        }
        if accepted and quantity is not None:
            if quantity_units is not None:
                event['quantity'] = quantity_units
            else:
                event['quantity'] = quantity
        if accepted and price is not None:
            event['price'] = self.json_number(price)
        if accepted and trigger_price is not None:
            event['trigger_price'] = self.json_number(trigger_price)
        self.record(event)
        if accepted:
            self.on_leg_modified(leg, before)
        return answer.outcome, answer.status_message, answer.response_body

    def outside_change_problem(self, leg, quantity_units):
        """Why a caller's change to one of this parent's legs cannot be made, or None when it can.

        Most types take any change the modify route has already checked. A type whose legs must stay within a position overrides this, so a change that would break that is refused before anything is sent.

        Args:
            leg (OrderLeg): The leg to be changed.
            quantity_units (int | None): The new quantity as the caller gave it, or None when the quantity is not changing.

        Returns:
            str | None: The reason, or None.
        """
        del leg, quantity_units
        return None

    def on_leg_modified(self, leg, before):
        """Lets the order type carry on from a change the caller made to one of its legs.

        The leg already holds the new quantity and prices. A type that keeps its own copy of a price or a quantity, such as a trailing stop's level or a chaser's step, overrides this to bring that copy in line, so its next tick works from the caller's values instead of moving the order back. Most types keep no copy and need nothing here.

        Args:
            leg (OrderLeg): The leg that was changed, holding its new values.
            before (dict): What the leg held before, with `quantity`, `price` and `trigger_price`.

        Returns:
            None: This method returns nothing.
        """
        del leg, before

    def record_parameters(self, reason):
        """Records the order type's parameters as they are now, so a restart replays them.

        A type that re-anchors itself after a caller's change, such as a peg taking a new offset, would otherwise keep the new value only in the Redis cache and lose it when recovery rebuilds the parent from the record.

        Args:
            reason (str): Why they changed, for a person reading the parent later.

        Returns:
            None: This method returns nothing.
        """
        self.record({
            'event': 'parameters_changed',
            'parent_state': self.parent.state,
            'status_message': reason,
            'detail': {
                'parameters': dict(self.parent.parameters),
            },
        })

    def cancel_by_caller(self, reason):
        """Cancels this parent because a caller asked: every leg still resting at a broker is cancelled, and the parent ends as `cancelled`.

        When a broker refuses a leg's cancel, or its outcome is unknown, that leg may still be live, so the parent is not called cancelled. It becomes `cancelling` instead: the order type no longer acts on it, and it ends as `cancelled` once every leg has finished. Cancelling it again retries the legs still resting.

        Args:
            reason (str): Why, for a person reading the parent later.

        Returns:
            list: One dictionary per leg a cancel was sent for, with `leg_id`, `broker`, `order_id`, `outcome` and `status_message`.
        """
        cancelled = []
        for leg in list(self.parent.legs):
            if leg.is_finished() or not leg.broker_order_id:
                continue
            outcome, status_message, _ = self.cancel_leg_answered(leg, reason)
            cancelled.append({
                'leg_id': leg.leg_id,
                'broker': leg.broker,
                'order_id': leg.broker_order_id,
                'outcome': outcome,
                'status_message': status_message,
            })
        still_resting = []
        for entry in cancelled:
            if entry['outcome'] != 'accepted':
                still_resting.append(f"{entry['broker']} {entry['order_id']}")
        if not still_resting:
            self.stop_acting(reason)
            return cancelled
        if self.parent.state != 'cancelling' and self.parent.can_change_to('cancelling'):
            self.record_state(
                'cancelling',
                f'{reason}; not yet cancelled at the broker: '
                + ', '.join(still_resting),
            )
            self.save()
        return cancelled

    def combined_answer(self, outcomes, statuses):
        """The outcome and HTTP status of an answer that combines several orders' answers.

        All accepted is `accepted` with 200. None accepted is `unknown` when any outcome is unknown and `rejected` otherwise, with the highest status. A mix is `partial` with 207, the status the list routes use for mixed results, so the caller knows to read each order's own outcome.

        Args:
            outcomes (list): Each order's outcome.
            statuses (list): Each order's HTTP status.

        Returns:
            tuple: The outcome (str) and the HTTP status (int).
        """
        if not outcomes:
            return 'accepted', 200
        accepted = 0
        for outcome in outcomes:
            if outcome == 'accepted':
                accepted = accepted + 1
        if accepted == len(outcomes):
            return 'accepted', max(statuses)
        if accepted > 0:
            return 'partial', 207
        if 'unknown' in outcomes:
            return 'unknown', max(statuses)
        return 'rejected', max(statuses)

    def finish_with_legs(self):
        """Ends the parent once every leg has finished, for a type that does nothing after placing its legs.

        The parent is `completed` when any leg traded and `cancelled` when none did. A leg still resting keeps it open.

        Returns:
            bool: True when the parent was ended on this call.
        """
        if not self.FINISHES_WITH_LEGS or self.parent.is_terminal():
            return False
        if not self.parent.legs:
            return False
        traded = 0
        for leg in self.parent.legs:
            if not leg.is_finished():
                return False
            traded = traded + (leg.filled_quantity or 0)
        if traded > 0:
            state = 'completed'
            reason = f'every order has finished, with {traded} traded'
        else:
            state = 'cancelled'
            reason = 'every order has finished without trading'
        if not self.parent.can_change_to(state):
            return False
        self.record_state(state, reason)
        self.save()
        return True

    def finish_cancelling(self):
        """Ends a `cancelling` parent as `cancelled` once none of its legs is still resting.

        Returns:
            bool: True when the parent was ended on this call.
        """
        if self.parent.state != 'cancelling':
            return False
        for leg in self.parent.legs:
            if not leg.is_finished() and leg.broker_order_id:
                return False
        self.record_state('cancelled', 'every leg has now finished')
        self.save()
        return True

    def stop_acting(self, reason):
        """Ends this parent as `cancelled` without touching its legs, so it places, moves and cancels nothing more.

        Flatten does this to every open parent before it cancels every order itself, so no trigger, bracket or schedule re-opens a position flatten is closing.

        Args:
            reason (str): Why, for a person reading the parent later.

        Returns:
            bool: True when the parent was open and is now cancelled.
        """
        if self.parent.is_terminal():
            return False
        if not self.parent.can_change_to('cancelled'):
            return False
        self.record_state('cancelled', reason)
        self.save()
        return True

    def cancel_outside_order(self, broker_name, broker_order_id, reason):
        """Cancels an order that is not one of this parent's legs, and records both the asking and the answer.

        A square-off cancels every order resting in the instruments it closes, wherever the order came from, so the order has no leg here to record against. The cancel is still recorded on this parent, before it is sent and after, and still takes a rate token, because an exchange counts it the same as any other cancel. The two events name the order by broker and broker order id, and replaying them changes nothing about the parent.

        Args:
            broker_name (str): The broker holding the order.
            broker_order_id (str): The broker's id for the order.
            reason (str): Why, for a person reading the parent later.

        Returns:
            bool: True when the broker accepted the cancel.
        """
        self.record({
            'event': 'outside_cancel_requested',
            'parent_state': self.parent.state,
            'broker': broker_name,
            'broker_order_id': broker_order_id,
            'status_message': reason,
        })
        outcome = None
        status_message = None
        response_body = None
        if self.gates is not None:
            try:
                self.gates.take_rate_token(broker_name)
            except RefusedRequestError as refusal:
                outcome = 'rejected'
                status_message = (
                    f'{reason}; not sent: {refusal.body.get("error")}'
                )
        if outcome is None:
            try:
                answer = self.placement.cancel(broker_name, broker_order_id)
                outcome = answer.outcome
                status_message = answer.status_message
                response_body = answer.response_body
            except RefusedRequestError as refusal:
                outcome = 'rejected'
                status_message = refusal.body.get('error')
            except Exception as error:
                outcome = 'unknown'
                status_message = f'the cancel could not be sent: {error}'
        self.record({
            'event': 'outside_cancelled',
            'parent_state': self.parent.state,
            'broker': broker_name,
            'broker_order_id': broker_order_id,
            'outcome': outcome,
            'status_message': status_message,
            'detail': {
                'broker_response': response_body,
            },
        })
        return outcome == 'accepted'

    def reduce_leg(self, leg, quantity, reason):
        """Reduces one leg's quantity at its broker, rather than cancelling and replacing it.

        This is the Atlas's rule for every linked pair: when one leg fills, reduce the other by what filled instead of cancelling it. Cancelling leaves a window with nothing protecting the position, and replacing loses the order's place in the queue.

        The quantity is in units, as every leg's quantity and fill are recorded, and is converted into the broker's own terms before it is sent, as a placement's is. Sending units unconverted asked a broker that counts commodities in lots for a quantity many times too large.

        Args:
            leg (OrderLeg): The leg to reduce.
            quantity (int): The new quantity, in units.
            reason (str): Why, for a person reading the parent later.

        Returns:
            bool: True when the broker accepted the change.
        """
        if quantity < 1:
            return self.cancel_leg(leg, reason)
        if not self.take_rate_token(leg, reason):
            return False
        try:
            broker_quantity = self.placement.broker_quantity(
                leg.broker,
                leg.instrument_id or self.parent.instrument_id,
                quantity,
            )
            answer = self.placement.modify_leg(
                leg.broker,
                leg.broker_order_id,
                quantity=broker_quantity,
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

        Moving a stop to breakeven after a first target fills works through this, and so will every type that re-prices a resting order. A leg whose cancel a broker has accepted is never moved: before, a peg or chaser kept modifying an order the caller had cancelled by its order id until the broker's update confirmed it.

        Args:
            leg (OrderLeg): The leg to move.
            price (decimal.Decimal | None): The new limit price, or None to leave it.
            trigger_price (decimal.Decimal | None): The new trigger price, or None to leave it.
            reason (str): Why, for a person reading the parent later.

        Returns:
            bool: True when the broker accepted the change.
        """
        if leg.cancel_accepted:
            return False
        if not self.moves_the_price(leg, price, trigger_price):
            return False
        if not self.allowed_to_reprice(leg, reason):
            return False
        if not self.has_room_today(leg, reason):
            return False
        if not self.take_rate_token(leg, reason):
            self.release_daily_place()
            return False
        try:
            answer = self.placement.modify_leg(
                leg.broker,
                leg.broker_order_id,
                price=price,
                trigger_price=trigger_price,
            )
        except Exception as error:
            self.release_daily_place()
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

    def has_room_today(self, leg, reason):
        """Whether a change to this leg's price fits in its broker's daily order cap.

        A modification counts against a broker's daily cap exactly as a placement does, so a type that re-prices an entry near the cap would spend the part of the cap kept for exits. So re-pricing an entry stops at the same point new entries do, and re-pricing an exit, such as a trailing stop ratcheting, may use the reserve. Cancels and quantity reductions are never held back here: refusing one could leave an order live that was meant to go.

        A refusal is recorded against the leg and returns False, as a rate budget refusal does.

        Args:
            leg (OrderLeg): The leg to be changed.
            reason (str): What the change was for, for the message.

        Returns:
            bool: True when the change may be sent.
        """
        if self.gates is None:
            return True
        try:
            self.gates.refuse_if_capped(
                leg.broker,
                self.closes_position(leg.role),
            )
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
        legs=None,
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
            legs (OrderLegs | None): Every leg of the strategy, when this leg is the one that chooses the broker, so the selector can check the broker can afford all of them. Only a basket passes this.

        Returns:
            tuple: The answer's body (dict), its HTTP status (int) and the leg's id (str).

        Raises:
            RefusedRequestError: For an order answered without calling a broker, including one the rate budget would not give a token to, one refused because its broker is too close to the day's order cap, and a leg of a reduce-only order that would not make its position smaller.
        """
        instrument_id = instrument_id or self.parent.instrument_id
        reduce_only = ReduceOnlyCheck(self.placement)
        if reduce_only.is_asked_for(self.parent.parameters):
            reduce_only.refuse_if_it_adds(order, instrument_id)
        if legs is None:
            prepared = self.placement.prepare(
                order,
                instrument_id,
                broker_name,
            )
        else:
            prepared = self.placement.prepare(
                order,
                instrument_id,
                broker_name,
                legs,
            )
        if self.gates is not None:
            self.gates.refuse_if_capped(
                prepared.broker_name,
                self.closes_position(role),
            )
        try:
            return self.record_and_send_leg(
                role,
                order,
                prepared,
                started_at,
                instrument_id,
            )
        except Exception:
            self.release_daily_place()
            raise

    def release_daily_place(self):
        """Gives back the daily cap place this thread counted for a message that was not sent.

        After a send the place has already been settled, so this changes nothing then.

        Returns:
            None: This method returns nothing.
        """
        if self.gates is not None:
            self.gates.release_reservation()

    def record_and_send_leg(self, role, order, prepared, started_at, instrument_id):
        """Records a leg as requested, takes a rate token, sends it and records the answer.

        Args:
            role (str): What the leg is for.
            order (PlaceOrderRequest): The order to send.
            prepared (PreparedPlacement): The chosen broker and the request built for it.
            started_at (float | None): `time.perf_counter()` when the engine took the intent, or None.
            instrument_id (str): The instrument the leg trades.

        Returns:
            tuple: The answer's body (dict), its HTTP status (int) and the leg's id (str).

        Raises:
            RefusedRequestError: When the rate budget gives no token.
        """
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

    @classmethod
    def carries_parent_overnight(cls, parent):
        """Whether recovery should rebuild a parent of this type from before today, which by default every parent of a type that sets `CARRIES_OVERNIGHT` is.

        Args:
            parent (ParentOrder): The parent rebuilt from the record.

        Returns:
            bool: True when the parent outlives the trading day.
        """
        del parent
        return cls.CARRIES_OVERNIGHT

    def closes_position(self, role):
        """Whether a leg closes a position, and so may use the part of a broker's daily cap kept for exits.

        Here a leg closes a position when the caller said so with `closes_position` in the order's parameters, which is how a plain order sent to get out of a position is told apart from one sent to get into it, since nothing else can tell. A plan adds the legs its own parts send to close or protect a position.

        Args:
            role (str): The leg's role, unused here.

        Returns:
            bool: True when the leg closes a position.
        """
        del role
        return self.parent.parameters.get('closes_position') is True

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
