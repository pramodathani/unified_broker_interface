"""The pricing that moves a resting stop through a table of profit milestones, ending in a trail."""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.trail_pricing import (
    TrailPricing,
)


class StagesPricing:
    """A plan order's stop that starts at `stop_price` and is moved by profit milestones, as today's stepped stop is.

    Each rule has a `gain`, measured from `entry_price` in the position's favour, and either `stop_at_gain`, where the stop goes measured the same way (0 is breakeven), or `trail_points`, which hands the rest of the trade to an ordinary trail. The stop rests at the broker the whole time and each milestone is a modify. A stop only ever moves in the position's favour, by at least `step_ticks`, so a rule that would loosen it counts as reached and is skipped. A trailing rule is the last one. How many rules have applied, and the trail once it has begun, are kept in the pricing's memory.

    Attributes:
        entry_price (decimal.Decimal): The price gains are measured from.
        stop_price (decimal.Decimal): Where the stop starts.
        limit_offset (decimal.Decimal): How far past the trigger the limit sits.
        step_ticks (int): The smallest move worth sending, in ticks.
        rules (list): The milestones, each a dictionary with `gain` and `stop_at_gain` or `trail_points`, all `decimal.Decimal`.
    """

    def __init__(self, entry_price, stop_price, limit_offset, step_ticks, rules):
        """Builds the pricing from settings the plan reader has already checked.

        Args:
            entry_price (decimal.Decimal): The price gains are measured from.
            stop_price (decimal.Decimal): Where the stop starts.
            limit_offset (decimal.Decimal): How far past the trigger the limit sits.
            step_ticks (int): The smallest move worth sending.
            rules (list): The milestones.

        Returns:
            None: This method returns nothing.
        """
        self.entry_price = entry_price
        self.stop_price = stop_price
        self.limit_offset = limit_offset
        self.step_ticks = step_ticks
        self.rules = rules

    def needs_prices(self):
        """Whether this pricing reads quotes, which it does.

        Returns:
            bool: True.
        """
        return True

    def moves(self):
        """Whether this pricing moves a resting order on later ticks, which it does.

        Returns:
            bool: True.
        """
        return True

    def limit_from(self, trigger, side):
        """The stop's limit, `limit_offset` past its trigger.

        Args:
            trigger (decimal.Decimal): The trigger.
            side (str): BUY or SELL, the side the stop trades.

        Returns:
            decimal.Decimal: The limit.
        """
        if side == 'SELL':
            return trigger - self.limit_offset
        return trigger + self.limit_offset

    def gain(self, price, side):
        """How far the price is from the entry in the position's favour.

        Args:
            price (decimal.Decimal): The last price.
            side (str): BUY or SELL, the side the stop trades, which is opposite to the position.

        Returns:
            decimal.Decimal: The gain, negative for a loss.
        """
        if side == 'SELL':
            return price - self.entry_price
        return self.entry_price - price

    def trail(self, memory):
        """The trail a trailing rule handed the stop to.

        Args:
            memory (dict): The pricing's memory, holding `trail_points`.

        Returns:
            TrailPricing: The trail.
        """
        return TrailPricing(decimal.Decimal(memory['trail_points']), None, self.limit_offset, self.step_ticks)

    def priced_body(self, plan_order, body, sending_side, quotes, memory):
        """The body as a stop-limit at `stop_price`, with no milestone applied yet.

        Args:
            plan_order (PlanOrder): The plan order, which rounds prices onto the tick.
            body (dict): A copy of the order's body, changed in place.
            sending_side (str): BUY or SELL, the side the stop trades.
            quotes (dict): The quotes, by instrument id.
            memory (dict): The pricing's memory, given `rules_applied`.

        Returns:
            dict | None: The body, or None when the prices cannot be rounded.
        """
        view = plan_order.view(quotes)
        trigger = view.rounded(self.stop_price, sending_side)
        if trigger is None:
            return None
        limit = view.rounded(self.limit_from(trigger, sending_side), sending_side)
        if limit is None or limit <= 0:
            return None
        memory['rules_applied'] = 0
        body['order_type'] = 'SL'
        body['trigger_price'] = str(trigger)
        body['price'] = str(limit)
        return body

    def carry_on(self, plan_order, memory, leg, before, quotes, now):
        """Keeps the caller's new trigger, moving the trail's best price only once a trailing rule has taken over.

        Before the trail starts the milestones are measured from `entry_price`, not from the stop, so the caller's trigger simply stands until a milestone moves the stop further. This keeps the rule of today's stepped stop.

        Args:
            plan_order (OrderContext): The plan order's context for this order.
            memory (dict): The pricing's memory, whose `best` is set in place once trailing.
            leg (OrderLeg): The stop, holding the caller's new trigger.
            before (dict): What the leg held before, with `trigger_price`.
            quotes (dict): Unused.
            now (float): Unused.

        Returns:
            str | None: What changed, for the event log, or None when nothing did.
        """
        if memory.get('trail_points') is None:
            return None
        return self.trail(memory).carry_on(plan_order, memory, leg, before, quotes, now)

    def moved_prices(self, plan_order, memory, leg, quotes, now):
        """Where the stop should move on this tick: to the milestone just reached, or after the best price once trailing.

        Args:
            plan_order (PlanOrder): The plan order, which reads quotes and knows the tick size.
            memory (dict): The pricing's memory, whose `rules_applied`, `trail_points` and `best` move on in place.
            leg (OrderLeg): The resting stop.
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            tuple | None: The new limit and trigger (decimal.Decimal) and a reason (str), or None.
        """
        if memory.get('trail_points') is not None:
            return self.trail(memory).moved_prices(plan_order, memory, leg, quotes, now)
        view = plan_order.view(quotes)
        if view.is_stale():
            return None
        price = view.last()
        if price is None:
            return None
        side = leg.transaction_type
        gain = self.gain(price, side)
        applied = int(memory.get('rules_applied') or 0)
        reached = applied
        wanted_gain = None
        trail_points = None
        for index in range(applied, len(self.rules)):
            rule = self.rules[index]
            if gain < rule['gain']:
                break
            reached = index + 1
            if 'trail_points' in rule:
                trail_points = rule['trail_points']
            else:
                wanted_gain = rule['stop_at_gain']
        if reached == applied:
            return None
        memory['rules_applied'] = reached
        if trail_points is not None:
            memory['trail_points'] = str(trail_points)
            memory['best'] = str(price)
            return self.trail(memory).moved_prices(plan_order, memory, leg, quotes, now)
        if wanted_gain is None:
            return None
        if side == 'SELL':
            wanted = self.entry_price + wanted_gain
        else:
            wanted = self.entry_price - wanted_gain
        trigger = view.rounded(wanted, side)
        if trigger is None:
            return None
        if leg.trigger_price is not None:
            current = decimal.Decimal(str(leg.trigger_price))
            step = plan_order.tick_size() * self.step_ticks
            if side == 'SELL' and trigger - current < step:
                return None
            if side == 'BUY' and current - trigger < step:
                return None
        limit = view.rounded(self.limit_from(trigger, side), side)
        if limit is None:
            return None
        return limit, trigger, f'milestone {reached} moves the stop to {trigger}'

    def described(self):
        """This pricing as a dry run shows it.

        Returns:
            dict: The settings.
        """
        rules = []
        for rule in self.rules:
            described = {}
            for name, value in rule.items():
                described[name] = str(value)
            rules.append(described)
        return {
            'stages': {
                'entry_price': str(self.entry_price),
                'stop_price': str(self.stop_price),
                'limit_offset': str(self.limit_offset),
                'step_ticks': self.step_ticks,
                'rules': rules,
            },
        }
