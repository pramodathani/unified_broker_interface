"""A position closed after a while, on the reasoning that a trade going nowhere has failed."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder
from unified_broker_interface.utilities.order_engine.utilities.exit_legs import (
    OPPOSITE_SIDES,
)
from unified_broker_interface.utilities.order_engine.utilities.moments import (
    Moments,
)


class TimeStop(SyntheticOrder):
    """An entry that closes itself at `until_time`, or `minutes` after it was placed.

    Two uses, one mechanism. A momentum trade that has gone nowhere in twenty minutes is a trade whose idea has failed, and holding it costs the capital without the thesis. And an intraday position has to be closed before the broker's own automatic square-off, which happens at a price nobody chose and often carries a charge.

    Whatever is still resting is cancelled **before** the position is closed, for the reason the kill switch exists: an entry still working while its position is being closed goes on opening the position that is being closed.

    What is closed is what actually filled, in the direction that closes it. Nothing here reads the account's positions, deliberately: this closes the position *this order* opened, and an account holding the same instrument from somewhere else is not this order's business to flatten.
    """

    SYNTHETIC_TYPE = 'time_stop'
    WANTS_CLOCK = True

    def run(self, intent, started_at):
        """Places the entry and records when to close it.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when neither `until_time` nor `minutes` is given, or the time has passed.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        close_at = self.close_at()
        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['close_at'] = close_at
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
        return body, status

    def close_at(self):
        """When the position is to be closed, as an epoch.

        Returns:
            float: The moment.

        Raises:
            RefusedRequestError: With HTTP 400 when neither setting is given, or the time has passed.
        """
        moments = Moments()
        parameters = self.parent.parameters
        if parameters.get('until_time') is not None:
            return moments.time_today(parameters['until_time'], 'until_time')
        if parameters.get('minutes') is not None:
            return moments.minutes_from_now(parameters['minutes'], 'minutes')
        raise RefusedRequestError.refusal(
            'a time_stop needs until_time, a time of day, or minutes, a '
            'number of minutes from now',
            400,
        )

    def on_clock_tick(self, now):
        """Cancels what is resting and closes what filled, once the time has come.

        Args:
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the parent acted on this tick.
        """
        close_at = self.parent.parameters.get('close_at')
        if not isinstance(close_at, (int, float)) or now < close_at:
            return False
        if self.closing_leg() is not None:
            return False

        entry = self.entry_leg()
        if entry is None:
            return False
        for leg in self.parent.live_legs():
            if leg.role == 'entry':
                self.cancel_leg(
                    leg,
                    'the time this order was given has run out, so the rest '
                    'of it is being stopped before the position is closed',
                )
        filled = entry.filled_quantity or 0
        if filled < 1:
            self.record_state(
                'cancelled',
                'the time ran out before anything filled',
            )
            self.save()
            return True
        self.place_closing_leg(entry, filled)
        return True

    def entry_leg(self):
        """This order's entry, or None.

        Returns:
            OrderLeg | None: The entry leg.
        """
        for leg in self.parent.legs:
            if leg.role == 'entry':
                return leg
        return None

    def closing_leg(self):
        """The leg that closes the position, once it exists.

        Returns:
            OrderLeg | None: The closing leg.
        """
        for leg in self.parent.legs:
            if leg.role == 'close':
                return leg
        return None

    def place_closing_leg(self, entry, filled):
        """Sends the order that closes what the entry filled.

        Args:
            entry (OrderLeg): The entry leg.
            filled (int): How much it filled, in the broker's own terms.

        Returns:
            None: This method returns nothing.
        """
        order = self.read_order(self.parent.body)
        closing = order.with_quantities(filled, 0)
        closing.transaction_type = OPPOSITE_SIDES[order.transaction_type]
        closing.order_type = 'MARKET'
        closing.price = None
        closing.price_text = '0'
        closing.price_number = 0.0
        closing.trigger_price = None
        closing.trigger_price_text = '0'
        closing.trigger_price_number = 0.0
        closing.tag = None
        body, _, _ = self.place_leg('close', closing, None, entry.broker)
        outcome = body.get('outcome')
        self.record_state(
            'completed' if outcome == 'accepted' else 'failed',
            body.get('status_message'),
        )
        self.save()
