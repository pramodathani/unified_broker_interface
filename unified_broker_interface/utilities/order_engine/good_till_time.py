"""An order that gives up at a time of day instead of resting until the close."""

from unified_broker_interface.utilities.order_engine.base import SyntheticOrder
from unified_broker_interface.utilities.order_engine.utilities.moments import (
    Moments,
)


class GoodTillTime(SyntheticOrder):
    """An order placed now and cancelled at `until_time` if it has not filled.

    Indian exchanges offer `DAY` and `IOC` and nothing between them, so an order that should stop trying at half past two either sits there until the close or has to be cancelled by somebody watching. This watches instead.

    Whatever has filled by then is kept. Only the part still resting is cancelled, which is what a caller means by giving up: they wanted a hundred, they got forty, and they would rather have forty than sixty more at a price that has moved away.
    """

    SYNTHETIC_TYPE = 'good_till_time'
    WANTS_CLOCK = True

    def run(self, intent, started_at):
        """Places the order and records when to give up on it.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when `until_time` is missing or has passed.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        until_time = Moments().time_today(
            self.parent.parameters.get('until_time'),
            'until_time',
        )
        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['cancel_at'] = until_time
        self.record_received()
        self.save()

        body, status, _ = self.place_leg('entry', order, started_at)
        outcome = body.get('outcome')
        state = {
            'accepted': 'working',
            'rejected': 'rejected',
        }.get(outcome, 'failed')
        self.record_state(state, body.get('status_message'))
        self.save()

        body['parent_id'] = self.parent.parent_order_id
        body['cancel_at'] = self.parent.parameters.get('until_time')
        return body, status

    def on_clock_tick(self, now):
        """Cancels whatever is still resting once the time has come.

        Args:
            now (float): The Unix time of the tick.

        Returns:
            bool: True when something was cancelled on this tick.
        """
        cancel_at = self.parent.parameters.get('cancel_at')
        if not isinstance(cancel_at, (int, float)) or now < cancel_at:
            return False
        acted = False
        for leg in self.parent.live_legs():
            self.cancel_leg(
                leg,
                'the order reached '
                f'{self.parent.parameters.get("until_time")} without filling',
            )
            acted = True
        if acted:
            self.record_state('cancelled', 'the time it was given ran out')
            self.save()
        return acted

    def on_leg_update(self, leg, changes):
        """Closes the parent when its order can do nothing more.

        Args:
            leg (OrderLeg): The leg that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        del leg, changes
        if self.parent.is_terminal() or self.parent.live_legs():
            return
        self.record_state('completed', None)
        self.save()
