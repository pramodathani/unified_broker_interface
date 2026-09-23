"""An entry that, once it fills, protects itself with a stop and a target watching each other."""

from unified_broker_interface.utilities.order_engine.oco import OneCancelsOther
from unified_broker_interface.utilities.order_engine.utilities.exit_legs import (
    ExitLegs,
)


class Bracket(OneCancelsOther):
    """An entry, then a stop and a target for whatever the entry filled.

    Flattrade's own description of the product it no longer offers through its API: a three-leg order where the target and the stop-loss cancel each other. Rebuilding it here is the clearest reason the order engine exists, because none of it can be expressed in a single request.

    It subclasses the OCO because the second half *is* an OCO. What a bracket adds is the entry and the arming, and the rules for those come from the Atlas:

    **The exits are armed on the first partial fill, not when the entry completes.** An entry for a hundred that fills ten leaves ten units exposed, and waiting for the other ninety before protecting them is the mistake that makes a bracket worse than two separate orders. Each further fill grows the exits rather than adding new ones.

    **When an exit fills while the entry is still working, the rest of the entry is cancelled first.** Otherwise the entry goes on filling into a position the exits have already been sized for, and the account ends up long with nothing protecting the difference.

    `transaction_type` is the entry's side. A bracket around a buy has sells for its stop and its target.
    """

    SYNTHETIC_TYPE = 'bracket'

    def run(self, intent, started_at):
        """Places the entry. The exits follow when it fills.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For an order answered without calling a broker.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        # Built and thrown away, so a bracket whose exit prices are unusable is refused before its
        # entry reaches a broker rather than after, when there would be an unprotected position.
        ExitLegs().build(order, self.parent.parameters, order.quantity)

        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.record_received()
        self.save()

        body, status, _ = self.place_leg('entry', order, started_at)
        outcome = body.get('outcome')
        if outcome == 'accepted':
            state = 'working'
        elif outcome == 'rejected':
            state = 'rejected'
        else:
            state = 'failed'
        self.record_state(state, body.get('status_message'))
        self.save()

        body['parent_id'] = self.parent.parent_order_id
        return body, status

    def on_leg_update(self, leg, changes):
        """Arms or grows the exits when the entry fills, and runs the OCO rules once they are resting.

        Args:
            leg (OrderLeg): The leg that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        if leg.role == 'entry':
            self.on_entry_update(leg, changes)
            return
        self.on_exit_update(leg, changes)

    def on_entry_update(self, leg, changes):
        """Protects whatever the entry has filled so far.

        Args:
            leg (OrderLeg): The entry leg.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        filled = leg.filled_quantity or 0
        if filled < 1:
            if changes.get('leg_state') in ('rejected', 'cancelled'):
                self.finish_if_done()
            return
        exits = self.exit_legs()
        if exits:
            self.grow_exits(exits, filled)
            return
        self.arm_exits(leg, filled)

    def exit_legs(self):
        """The stop and target legs, once they exist.

        Returns:
            list: The exit legs, which may be empty.
        """
        found = []
        for leg in self.parent.legs:
            if leg.role in ('stop', 'target'):
                found.append(leg)
        return found

    def arm_exits(self, entry, filled):
        """Places the stop and the target for what the entry has filled.

        Args:
            entry (OrderLeg): The entry leg.
            filled (int): How much has filled, in the broker's own terms.

        Returns:
            None: This method returns nothing.
        """
        order = self.read_order(self.parent.body)
        legs = ExitLegs().build(order, self.parent.parameters, filled)
        for role, exit_order in legs:
            # Every leg to the broker the entry went to: the position is there, and an exit
            # anywhere else would be a new position rather than a way out of this one.
            self.place_leg(role, exit_order, None, entry.broker)
        self.record_state('protecting', None)
        self.save()

    def grow_exits(self, exits, filled):
        """Brings the exits up to what the entry has now filled.

        Args:
            exits (list): The exit legs.
            filled (int): How much the entry has filled, in the broker's own terms.

        Returns:
            None: This method returns nothing.
        """
        for leg in exits:
            if leg.is_finished():
                continue
            already = leg.filled_quantity or 0
            wanted = filled - already
            if wanted == leg.quantity or wanted < 1:
                continue
            self.reduce_leg(
                leg,
                wanted,
                f'the entry has now filled {filled}, so this leg follows it',
            )
        self.save()

    def on_exit_update(self, leg, changes):
        """Runs the OCO rules, and stops the entry filling into a position the exits are done with.

        Args:
            leg (OrderLeg): The exit leg that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        if changes.get('filled_quantity') is not None:
            self.cancel_working_entry(leg)
            self.rebalance(leg)
        self.finish_if_done()

    def cancel_working_entry(self, exit_leg):
        """Cancels whatever is left of the entry once an exit has started filling.

        An entry still working while the position is being closed goes on buying into a position the exits have already been sized for, and the difference ends up unprotected. Cancelling it is the Atlas's rule and it comes before reducing the sibling, because the entry is the one that can still grow the problem.

        Args:
            exit_leg (OrderLeg): The exit that filled.

        Returns:
            None: This method returns nothing.
        """
        for leg in self.parent.legs:
            if leg.role != 'entry' or leg.is_finished() or not leg.is_live():
                continue
            self.cancel_leg(
                leg,
                f'the {exit_leg.role} has started filling, so the rest of the '
                'entry is being stopped',
            )
