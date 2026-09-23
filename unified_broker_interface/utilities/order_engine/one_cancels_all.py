"""Several candidate entries, of which the first to fill cancels the rest."""

from unified_broker_interface.utilities.order_engine.basket import Basket


class OneCancelsAll(Basket):
    """A group of entries where whichever triggers first is the trade and the others are called off.

    "Enter whichever of these setups fires first." Three breakout levels across three stocks, or the same level on a call and a put, where the plan was always to take one position and the market decides which.

    It is a basket in how it is placed and a one-cancels-other in how it lives, so it subclasses the first and borrows the second's discipline. The moment any leg reports a fill — including a partial one — every other leg is cancelled.

    **A double fill is possible and cannot be made impossible.** This is the same problem the two-legged types have, made worse by having more legs: in a fast market several candidates can fill before any cancel arrives, and the account ends up in two or three positions where it wanted one. The Atlas is direct that more legs mean a higher chance of it.

    What is done about it is what can be done. The cancels go out on the first sign of a fill rather than on a complete one, so the window is as short as reading an update allows. Every cancel and every fill is in the event log, so an account that ends up in two positions says so plainly rather than being discovered at the end of the day. And the answer carries the parent id, so somebody can look.

    The legs are not reduced the way an OCO's are, because they are not exits on one position. They are separate candidate trades, and half a candidate trade is not something anybody wanted.
    """

    SYNTHETIC_TYPE = 'oca'

    def on_leg_update(self, leg, changes):
        """Cancels every other candidate as soon as one of them fills.

        Args:
            leg (OrderLeg): The leg that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        if leg.role != 'basket':
            return
        if not leg.filled_quantity:
            self.finish_if_done()
            return
        for other in self.parent.legs:
            if other.leg_id == leg.leg_id or other.is_finished():
                continue
            if other.broker_order_id is None:
                continue
            self.cancel_leg(
                other,
                f'the candidate on {leg.instrument_id} filled '
                f'{leg.filled_quantity}, so this one is called off',
            )
        if not self.parent.is_terminal():
            self.record_state(
                'protecting',
                f'the candidate on {leg.instrument_id} is the trade',
            )
        self.save()

    def finish_if_done(self):
        """Closes the parent once none of the candidates can still fill.

        Returns:
            None: This method returns nothing.
        """
        if self.parent.is_terminal():
            return
        if self.parent.live_legs():
            return
        self.record_state('completed', 'no candidate is still working')
        self.save()
