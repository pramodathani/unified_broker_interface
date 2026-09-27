"""An order that gives up at a time of day instead of resting until the close."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder
from unified_broker_interface.utilities.order_engine.utilities.moments import (
    Moments,
)

DEFAULT_BUFFER_TICKS = 2
EXPIRY_ACTIONS = (
    'cancel',
    'market',
)


class GoodTillTime(SyntheticOrder):
    """An order placed now and cancelled at `until_time` if it has not filled.

    Indian exchanges offer `DAY` and `IOC` and nothing between them, so an order that should stop trying at half past two either sits there until the close or has to be cancelled by somebody watching. This watches instead.

    Whatever has filled by then is kept. Only the part still resting is cancelled, which is what a caller means by giving up: they wanted a hundred, they got forty, and they would rather have forty than sixty more at a price that has moved away.

    With `at_expiry` set to `market`, the rest is made marketable at `until_time` instead of cancelled: the order works as a limit until then, and whatever has not filled is moved to a price two ticks past the other side of the book, so it fills. This is the Atlas's limit-then-market order (G5), which Interactive Brokers sells as Funari. Indian brokers turn API market orders into limits with market protection anyway, so a marketable limit is what a market order would become.
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
            RefusedRequestError: With HTTP 400 when `until_time` is missing or has passed, or `at_expiry` is not `cancel` or `market`.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        moments = Moments()
        until_time, until_day = moments.time_on_trading_day(
            self.parent.parameters.get('until_time'),
            'until_time',
            self.trading_segment(),
        )
        self.read_expiry_action()
        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['cancel_at'] = until_time
        if self.read_expiry_action() == 'market':
            self.remember_tick_size(order)
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
        body['cancel_at'] = moments.described(
            self.parent.parameters.get('until_time'),
            until_day,
        )
        return body, status

    def read_expiry_action(self):
        """What to do with the part still resting when the time runs out.

        Returns:
            str: `cancel`, the default, or `market`.

        Raises:
            RefusedRequestError: With HTTP 400 for anything else.
        """
        action = self.parent.parameters.get('at_expiry') or 'cancel'
        if action not in EXPIRY_ACTIONS:
            raise RefusedRequestError.refusal(
                f'at_expiry must be one of {", ".join(EXPIRY_ACTIONS)}, not {action!r}',
                400,
            )
        return action

    def on_clock_tick(self, now):
        """Cancels whatever is still resting once the time has come, or makes it marketable when `at_expiry` says so.

        Args:
            now (float): The Unix time of the tick.

        Returns:
            bool: True when something was cancelled on this tick.
        """
        cancel_at = self.parent.parameters.get('cancel_at')
        if not isinstance(cancel_at, (int, float)) or now < cancel_at:
            return False
        if self.parent.parameters.get('at_expiry') == 'market':
            return self.make_marketable()
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

    def make_marketable(self):
        """Moves every resting leg to a price two ticks past the other side of the book, once.

        Returns:
            bool: True when a leg was moved on this tick.
        """
        if self.parent.parameters.get('made_marketable'):
            return False
        try:
            _, quote, _ = self.placement.market_context(
                self.parent.instrument_id,
                True,
                False,
            )
        except RefusedRequestError as refusal:
            self.logger.warning(
                f'Parent {self.parent.parent_order_id} could not read the quote '
                f'to make its order marketable: {refusal.body.get("error")}'
            )
            return False
        view = self.view({
            self.parent.instrument_id: quote,
        })
        acted = False
        for leg in self.parent.live_legs():
            touch = view.opposite_touch(leg.transaction_type)
            if touch is None:
                touch = view.last()
            if touch is None:
                continue
            price = view.rounded(
                view.moved(touch, DEFAULT_BUFFER_TICKS, leg.transaction_type, True),
                leg.transaction_type,
            )
            if price is None or price <= 0:
                continue
            moved = self.reprice_leg(
                leg,
                price,
                None,
                f'the order reached {self.parent.parameters.get("until_time")}, '
                'so what is left is made marketable',
            )
            if moved:
                acted = True
        if acted:
            self.parent.parameters = dict(self.parent.parameters)
            self.parent.parameters['made_marketable'] = True
            self.record_parameters('the rest of the order was made marketable at its time')
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
