"""A stop on a position that moves to set levels as the trade reaches set profits."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.trailing_stop import (
    TrailingStop,
)

MOST_RULES = 20


class SteppedStop(TrailingStop):
    """A native stop-limit whose trigger is moved by a table of profit milestones (the Atlas's G8, an adjustable stop or stop strategy).

    A common way to manage a trade is a short table: once it is 20 points in profit move the stop to breakeven, at 40 lock in 15, at 60 start trailing 25 behind. Each row is a rule with a `gain` measured from `entry_price` in the position's favour, and either `stop_at_gain`, where to put the stop measured the same way (0 is breakeven, a negative number still risks something), or `trail_points`, which switches the rest of the trade to an ordinary trailing stop.

    The stop rests at the broker the whole time, as every stop in this engine does, and each step is a modify. A stop is only ever moved in the position's favour, so a rule that would loosen it is recorded as reached and skipped. A trailing rule has to be the last one, because after it the trail is in charge.

    `transaction_type` is the side that opened the position, as for `trailing_stop`, so a long is protected by asking for a BUY and the stop placed is a sell.
    """

    SYNTHETIC_TYPE = 'stepped_stop'

    def required_price(self, name):
        """One price the caller must give.

        Args:
            name (str): The parameter's name.

        Returns:
            decimal.Decimal: The price.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or is not a number above zero.
        """
        value = self.parent.parameters.get(name)
        if value is None:
            raise RefusedRequestError.refusal(
                f'a stepped stop needs {name}',
                400,
            )
        return self.positive(value, name)

    def read_rules(self):
        """The milestone table, checked and in order.

        Returns:
            list: One dict per rule, with `gain` (decimal.Decimal) and either `stop_at_gain` or `trail_points` (decimal.Decimal).

        Raises:
            RefusedRequestError: With HTTP 400 when the table is empty or too long, a gain is not above zero or not larger than the one before, a rule has both or neither of `stop_at_gain` and `trail_points`, a stop would sit at or past its own gain, or a trailing rule is not the last.
        """
        given = self.parent.parameters.get('rules')
        if not isinstance(given, list) or not given or len(given) > MOST_RULES:
            raise RefusedRequestError.refusal(
                f'a stepped stop needs rules, a list of 1 to {MOST_RULES} '
                'milestones',
                400,
            )
        rules = []
        previous_gain = decimal.Decimal(0)
        for position, rule in enumerate(given, start=1):
            if not isinstance(rule, dict):
                raise RefusedRequestError.refusal(
                    f'rule {position} must be an object with gain and '
                    'stop_at_gain or trail_points',
                    400,
                )
            gain = self.positive(rule.get('gain'), f'rule {position} gain')
            if gain <= previous_gain:
                raise RefusedRequestError.refusal(
                    f'rule {position} gain of {gain} must be larger than the '
                    'rule before it',
                    400,
                )
            has_stop = rule.get('stop_at_gain') is not None
            has_trail = rule.get('trail_points') is not None
            if has_stop == has_trail:
                raise RefusedRequestError.refusal(
                    f'rule {position} needs exactly one of stop_at_gain and '
                    'trail_points',
                    400,
                )
            checked = {
                'gain': gain,
            }
            if has_trail:
                if position != len(given):
                    raise RefusedRequestError.refusal(
                        f'rule {position} switches to trailing, so it must be '
                        'the last rule',
                        400,
                    )
                checked['trail_points'] = self.positive(
                    rule['trail_points'],
                    f'rule {position} trail_points',
                )
            else:
                try:
                    stop_at_gain = decimal.Decimal(str(rule['stop_at_gain']))
                except (decimal.InvalidOperation, TypeError, ValueError):
                    raise RefusedRequestError.refusal(
                        f'rule {position} stop_at_gain must be a number, not '
                        f'{rule["stop_at_gain"]!r}',
                        400,
                    )
                if stop_at_gain >= gain:
                    raise RefusedRequestError.refusal(
                        f'rule {position} would put the stop at {stop_at_gain}, '
                        f'at or past the gain of {gain} that moves it, where '
                        'it would fire at once',
                        400,
                    )
                checked['stop_at_gain'] = stop_at_gain
            rules.append(checked)
            previous_gain = gain
        return rules

    def run(self, intent, started_at):
        """Places the first stop at `stop_price`.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 for a missing or bad entry price, stop price, offset, step or rule table, or a trail or activation given outside the rules, and 503 when there is no tick size.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        for name in ('trail_points', 'trail_percent', 'activate_at'):
            if self.parent.parameters.get(name) is not None:
                raise RefusedRequestError.refusal(
                    f'a stepped stop trails only through a rule, so it does '
                    f'not take {name} on its own',
                    400,
                )
        self.required_price('entry_price')
        stop_price = self.required_price('stop_price')
        self.read_limit_offset()
        self.read_step_ticks()
        self.read_rules()

        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.remember_tick_size(order)
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['rules_applied'] = 0
        self.record_received()
        self.save()
        leg_side = self.leg_side(order.transaction_type)
        view = self.view({})
        trigger = view.rounded(stop_price, leg_side)
        limit = view.rounded(self.limit_from(trigger, leg_side), leg_side)
        body, status, _ = self.place_leg(
            'stop',
            self.stop_order(order, trigger, limit, leg_side),
            started_at,
        )
        outcome = body.get('outcome')
        state = {
            'accepted': self.ARMED_STATE,
            'rejected': 'rejected',
        }.get(outcome, 'failed')
        self.record_state(state, body.get('status_message'))
        self.save()
        body['parent_id'] = self.parent.parent_order_id
        return body, status

    def on_price_tick(self, quotes, now):
        """Applies every milestone the market has reached, or trails once a trailing rule has been reached.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the stop was moved.
        """
        leg = self.resting_stop()
        if leg is None:
            return False
        if self.parent.parameters.get('trail_points') is not None:
            return super().on_price_tick(quotes, now)
        view = self.view(quotes)
        price = view.last()
        if price is None:
            return False
        entry = self.required_price('entry_price')
        if leg.transaction_type == 'SELL':
            gain = price - entry
        else:
            gain = entry - price
        rules = self.read_rules()
        applied = int(self.parent.parameters.get('rules_applied') or 0)
        reached = applied
        wanted_gain = None
        trail_points = None
        for index in range(applied, len(rules)):
            rule = rules[index]
            if gain < rule['gain']:
                break
            reached = index + 1
            if 'trail_points' in rule:
                trail_points = rule['trail_points']
            else:
                wanted_gain = rule['stop_at_gain']
        if reached == applied:
            return False

        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['rules_applied'] = reached
        if trail_points is not None:
            self.parent.parameters['trail_points'] = str(trail_points)
            self.parent.parameters['watermark'] = str(price)
            self.record_parameters(
                f'the trade is {gain} in profit, so the stop now trails '
                f'{trail_points} behind'
            )
            self.save()
            return super().on_price_tick(quotes, now)
        self.record_parameters(
            f'the trade is {gain} in profit, so milestone {reached} applies'
        )
        self.save()

        if leg.transaction_type == 'SELL':
            wanted = entry + wanted_gain
        else:
            wanted = entry - wanted_gain
        trigger = view.rounded(wanted, leg.transaction_type)
        if trigger is None:
            return False
        if not self.improves_trigger(trigger, leg, self.tick_size()):
            return False
        limit = view.rounded(
            self.limit_from(trigger, leg.transaction_type),
            leg.transaction_type,
        )
        moved = self.reprice_leg(
            leg,
            limit,
            trigger,
            f'milestone {reached} moves the stop to {trigger}',
        )
        if moved:
            self.save()
        return moved

    def on_leg_modified(self, leg, before):
        """Keeps a caller's new trigger, re-anchoring the trail only once a trailing rule has taken over.

        Before the trail starts the milestones are measured from `entry_price`, not from the stop, so the caller's trigger simply stands until a milestone moves the stop further.

        Args:
            leg (OrderLeg): The stop, holding its new trigger.
            before (dict): What the leg held before, with `trigger_price`.

        Returns:
            None: This method returns nothing.
        """
        if self.parent.parameters.get('trail_points') is None:
            return
        super().on_leg_modified(leg, before)
