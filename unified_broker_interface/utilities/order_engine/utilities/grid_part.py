"""A plan order kept whole as a grid: buy limits below the market and sell limits above it, each fill placing its opposite one step away."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.whole_part import (
    WholePart,
)

MOST_LEVELS = 20
OPPOSITE_SIDES = {
    'BUY': 'SELL',
    'SELL': 'BUY',
}


class GridPart(WholePart):
    """A grid in a plan, with the rules of today's grid type.

    `levels` orders go out on each side, `step_points` apart, around the last traded price when the plan is placed, and the body's quantity is the size of each one. When a rung fills, its opposite is placed one step away: a buy filled at 995 is followed by a sell at 1000. `most_inventory` is required: once the net position the grid's fills have built reaches it, every resting rung on the side that would make it bigger is cancelled, so a trending market cannot keep adding to the losing side. Each filled rung's leg id is remembered once it has been answered, so a restart never places its opposite twice.
    """

    def _number_setting(self, name, problems):
        """One setting read as a number, with a problem when it is missing or not a number.

        Args:
            name (str): The setting's name.
            problems (list): The problems found so far, added to in place.

        Returns:
            decimal.Decimal | None: The value, or None when it has a problem.
        """
        value = self.settings.get(name)
        if isinstance(value, bool):
            problems.append(f'{name} must be a number, not {value!r}')
            return None
        try:
            number = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            problems.append(f'{name} must be a number, not {value!r}')
            return None
        if not number.is_finite():
            problems.append(f'{name} must be a number, not {value!r}')
            return None
        return number

    def settings_problems(self):
        """Every problem with `levels`, `step_points` and `most_inventory`, in today's words.

        Returns:
            list: One message (str) per problem.
        """
        problems = []
        for name in self.settings:
            if name not in ('levels', 'step_points', 'most_inventory'):
                problems.append(f'the grid preset takes levels, step_points and most_inventory, not {name!r}')
        if self.settings.get('levels') is None:
            problems.append('a grid needs levels, how many orders go out on each side')
        else:
            levels = self._number_setting('levels', problems)
            if levels is not None and (levels != levels.to_integral_value() or levels < 1 or levels > MOST_LEVELS):
                problems.append(f'levels must be a whole number between 1 and {MOST_LEVELS}, not {self.settings.get("levels")}')
        if self.settings.get('step_points') is None:
            problems.append('a grid needs step_points, the gap between one level and the next')
        else:
            step = self._number_setting('step_points', problems)
            if step is not None and step <= 0:
                problems.append(f'step_points must be above zero, not {step}')
        if self.settings.get('most_inventory') is None:
            problems.append('a grid needs most_inventory: a trending market fills one side over and over, and without a cap the position keeps growing at prices that keep getting worse')
        else:
            most = self._number_setting('most_inventory', problems)
            if most is not None and (most != most.to_integral_value() or most < 1):
                problems.append(f'most_inventory must be a whole number of at least one, not {self.settings.get("most_inventory")}')
        return problems

    def levels(self):
        """How many orders go out on each side.

        Returns:
            int: The count.
        """
        return int(self.settings['levels'])

    def step(self):
        """The gap between one level and the next.

        Returns:
            decimal.Decimal: The step, in price.
        """
        return decimal.Decimal(str(self.settings['step_points']))

    def most_inventory(self):
        """The largest net position the grid may hold in either direction.

        Returns:
            int: The cap in units.
        """
        return int(self.settings['most_inventory'])

    def needs_prices(self):
        """Whether this part reads quotes, which it does to find the middle of the grid.

        Returns:
            bool: True.
        """
        return True

    def prepared_own_memory(self, plan_order):
        """The price the grid is built around, read when the plan is placed: the last traded price.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            dict: `centre`, the price as a string, and `answered`, the filled rungs answered so far.

        Raises:
            RefusedRequestError: With HTTP 503 when the live quote carries no last traded price, or the brokers do not agree on a tick size.
        """
        context = self.context(plan_order)
        instrument, quote, _ = context.placement.market_context(context.instrument_id, True, False)
        tick_size = plan_order.read_order(context.body).agreed_tick_size(instrument.handles)
        middle = MarketView(quote, tick_size).last()
        if middle is None:
            raise RefusedRequestError.refusal(
                'a grid is built around where the market is and the live quote does not carry a last traded price yet',
                503,
                instrument_id=context.instrument_id,
            )
        return {
            'centre': str(middle),
            'answered': [],
        }

    def start(self, plan_order, target, started_at, quotes, now=None):
        """Places the whole ladder, both sides, around the price remembered when the plan was placed.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int | None): Unused, since a grid trades no total: each rung is the body's quantity.
            started_at (float | None): When the engine took the intent, or None.
            quotes (dict): The quotes, whose tick size rounds each rung.
            now (float | None): Unused.

        Returns:
            list: One `(path, answer, status)` per rung placed.
        """
        del target, now
        record = plan_order.part_record(self.path)
        record['state'] = 'working'
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} grid is set around {self.own_memory(plan_order)["centre"]}')
        middle = decimal.Decimal(self.own_memory(plan_order)['centre'])
        view = self.context(plan_order).view(quotes)
        step = self.step()
        placed = []
        for index in range(1, self.levels() + 1):
            for side in ('BUY', 'SELL'):
                if side == 'BUY':
                    price = view.rounded(middle - step * index, 'BUY')
                else:
                    price = view.rounded(middle + step * index, 'SELL')
                if price is None or price <= 0:
                    continue
                body, status, _ = self.place_order(plan_order, self.limit_order(plan_order, side, price), started_at)
                placed.append((self.path, body, status))
        return placed

    def inventory(self, parent):
        """The net position the grid's own fills have built.

        Args:
            parent (ParentOrder): The plan order's parent.

        Returns:
            int: Positive when long.
        """
        net = 0
        for leg in self.own_legs(parent):
            filled = leg.filled_quantity or 0
            if leg.transaction_type == 'BUY':
                net = net + filled
            else:
                net = net - filled
        return net

    def stop_adding(self, plan_order):
        """Cancels the resting rungs that would make the position bigger, once it has reached its cap.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            None: This method returns nothing.
        """
        net = self.inventory(plan_order.parent)
        if abs(net) < self.most_inventory():
            return
        adding = 'BUY' if net > 0 else 'SELL'
        for leg in self.own_legs(plan_order.parent):
            if leg.is_finished() or leg.transaction_type != adding or leg.broker_order_id is None:
                continue
            plan_order.cancel_leg(leg, f'the grid is holding {net}, which is its whole allowance, so it stops adding to that side')

    def settle(self, plan_order):
        """Places the opposite of every rung that has filled and not been answered yet, then stops adding past the cap.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            list: One `(path, answer, status)` per rung placed.
        """
        record = plan_order.part_record(self.path)
        if record.get('state') != 'working':
            return []
        memory = self.own_memory(plan_order)
        answered = list(memory.get('answered') or [])
        newly_filled = []
        for leg in self.own_legs(plan_order.parent):
            if leg.state == 'filled' and leg.price is not None and leg.leg_id not in answered:
                newly_filled.append(leg)
        placed = []
        for leg in newly_filled:
            answered.append(leg.leg_id)
            memory['answered'] = answered
            self.remember(plan_order, memory, f'the plan\'s {self.path} grid answers the rung {leg.leg_id} that filled')
            side = OPPOSITE_SIDES[leg.transaction_type]
            filled_at = decimal.Decimal(str(leg.price))
            price = filled_at + self.step() if side == 'SELL' else filled_at - self.step()
            if price > 0:
                body, status, _ = self.place_order(plan_order, self.limit_order(plan_order, side, price), None)
                placed.append((self.path, body, status))
        if newly_filled:
            self.stop_adding(plan_order)
        reason = self.done_reason(plan_order.parent)
        if reason is not None:
            record = plan_order.part_record(self.path)
            record['state'] = 'done'
            record['reason'] = reason
            plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part is done: {reason}')
        return placed
