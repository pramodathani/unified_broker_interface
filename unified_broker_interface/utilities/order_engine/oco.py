"""Two exits on one position, where whatever fills first reduces the other."""

from unified_broker_interface.utilities.order_engine.base import SyntheticOrder
from unified_broker_interface.utilities.order_engine.utilities.exit_legs import (
    ExitLegs,
)


class OneCancelsOther(SyntheticOrder):
    """A stop and a target resting together, each shrinking as the other fills.

    The caller already holds the position; this protects it. `transaction_type` is the side that **opened** it, so a long is protected by asking for a BUY, and both exits are sells.

    **The recurring bug in every linked pair is the double fill**, and this is written around avoiding it. Both exits rest at the exchange, so in a fast market both can fill before any cancel arrives, and the account ends up with a position twice the size it started with, in the opposite direction, unattended.

    Three things follow from that, all of them from the Atlas:

    The sibling is *reduced* by what filled, never cancelled and replaced. Cancelling leaves a window with nothing protecting the position; replacing loses the order's place in the queue and sends two orders where one change would do.

    A fill is acted on the moment it is seen, including a partial one. Waiting for a leg to fill completely means the sibling is oversized for however long the rest takes.

    And when the position is closed, whatever is left of the other leg is cancelled rather than left to expire, because an exit that outlives its position opens a new one.

    The engine cannot make a double fill impossible — only the exchange could, and it offers no such order — so what is left is to make the window as small as reading an update allows, and to make the answer visible in the event log when it happens anyway.
    """

    SYNTHETIC_TYPE = 'oco'

    def run(self, intent, started_at):
        """Places both exits and answers with what the brokers said.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For an order answered without calling a broker.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        legs = ExitLegs().build(order, self.parent.parameters, order.quantity)

        if order.dry_run:
            prepared = self.placement.prepare(
                legs[0][1],
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.record_received()
        self.save()

        answers = []
        broker_name = None
        for role, exit_order in legs:
            body, status, _ = self.place_leg(
                role,
                exit_order,
                started_at,
                broker_name,
            )
            if broker_name is None:
                broker_name = body.get('broker')
            answers.append((role, body, status))
        self.settle(answers)
        return self.answer(answers, broker_name)

    def on_leg_update(self, leg, changes):
        """Reduces the other exit by whatever this one filled, or cancels it when the position is closed.

        Args:
            leg (OrderLeg): The leg that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        if leg.role not in ('stop', 'target'):
            return
        if changes.get('filled_quantity') is None:
            if changes.get('leg_state') in ('rejected', 'cancelled'):
                self.finish_if_done()
            return
        self.rebalance(leg)
        self.finish_if_done()

    def rebalance(self, filled_leg):
        """Brings the other exit down to what is still open, after this one filled some of it.

        Args:
            filled_leg (OrderLeg): The leg that filled.

        Returns:
            None: This method returns nothing.
        """
        for leg in self.parent.legs:
            if leg.leg_id == filled_leg.leg_id or leg.is_finished():
                continue
            if leg.role not in ('stop', 'target'):
                continue
            remaining = (leg.quantity or 0) - (filled_leg.filled_quantity or 0)
            if remaining == leg.quantity:
                continue
            self.reduce_leg(
                leg,
                remaining,
                f'{filled_leg.role} filled '
                f'{filled_leg.filled_quantity}, so this leg follows it down',
            )
        self.save()

    def finish_if_done(self):
        """Closes the parent once nothing it placed can still fill.

        Returns:
            None: This method returns nothing.
        """
        if self.parent.is_terminal():
            return
        if self.parent.live_legs():
            return
        self.record_state('completed', None)
        self.save()

    def settle(self, answers):
        """Records the parent's state from what the exits did when they were placed.

        Args:
            answers (list): One `(role, body, status)` per exit.

        Returns:
            None: This method returns nothing.
        """
        outcomes = [body.get('outcome') for _, body, _ in answers]
        if 'unknown' in outcomes:
            state = 'failed'
        elif 'accepted' in outcomes:
            state = 'protecting'
        else:
            state = 'rejected'
        self.record_state(state, None)
        self.save()

    def answer(self, answers, broker_name):
        """The one answer the waiting API worker gets.

        Args:
            answers (list): One `(role, body, status)` per exit.
            broker_name (str | None): The broker both exits went to.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        bodies = [body for _, body, _ in answers]
        outcomes = [body.get('outcome') for body in bodies]
        outcome = 'accepted'
        if 'unknown' in outcomes:
            outcome = 'unknown'
        elif 'rejected' in outcomes:
            outcome = 'rejected'
        return {
            'broker': broker_name,
            'instrument_id': self.parent.instrument_id,
            'parent_id': self.parent.parent_order_id,
            'tag': self.parent.tag,
            'outcome': outcome,
            'legs': [
                {
                    'role': role,
                    'order_id': body.get('order_id'),
                    'outcome': body.get('outcome'),
                    'status_message': body.get('status_message'),
                }
                for role, body, _ in answers
            ],
            'skipped': bodies[0].get('skipped') if bodies else [],
            'timing_ms': bodies[0].get('timing_ms') if bodies else {},
        }, max(status for _, _, status in answers) if answers else 200
