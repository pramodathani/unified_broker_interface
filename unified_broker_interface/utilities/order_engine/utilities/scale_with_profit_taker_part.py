"""A plan order kept whole as a scale with profit-taker: a ladder that books each rung's profit and places the rung again."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.ladder_execution import (
    LadderExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.whole_part import (
    WholePart,
)

MOST_STEPS = 20
OPPOSITE_SIDES = {
    'BUY': 'SELL',
    'SELL': 'BUY',
}
SETTINGS = (
    'from_price',
    'to_price',
    'steps',
    'profit_points',
    'most_cycles',
)


class ScaleWithProfitTakerPart(WholePart):
    """A scale with profit-taker in a plan, with the rules of today's type.

    The rungs are placed as a ladder places them: `steps` limits on the body's side from `from_price` to `to_price`, sharing the body's quantity. When a rung has filled, a profit-taking limit for the same quantity goes out `profit_points` better: a sell above a filled buy, a buy below a filled sell. When that profit-taker fills, the rung is placed again at its own price, at most `most_cycles` times, or without a limit until the plan is cancelled. The position therefore never exceeds the ladder's own quantity.

    Its memory holds each rung's price, quantity and cycles, which rung each of its broker orders belongs to, and which fills it has answered, so a restart answers nothing twice. A rung is told from a profit-taker by its side. Unlike today's type, it is done once every one of its broker orders has finished, which happens only after the last cycle allowed has been taken.
    """

    def settings_problems(self):
        """Every problem with the settings, in today's words.

        Returns:
            list: One message (str) per problem.
        """
        problems = []
        for name in self.settings:
            if name not in SETTINGS:
                problems.append(f'the scale_with_profit_taker preset takes {", ".join(SETTINGS)}, not {name!r}')
        steps = self._whole('steps')
        if steps is None or steps < 2 or steps > MOST_STEPS:
            problems.append(f'a ladder needs steps between 2 and {MOST_STEPS}, not {self.settings.get("steps")!r}')
        from_price = self._positive('from_price')
        to_price = self._positive('to_price')
        if from_price is None:
            problems.append('a ladder needs from_price above zero')
        if to_price is None:
            problems.append('a ladder needs to_price above zero')
        if from_price is not None and from_price == to_price:
            problems.append('a ladder needs from_price and to_price to differ')
        if self._positive('profit_points') is None:
            problems.append(f'a scale with profit-taker needs profit_points, the distance above zero to take each rung\'s profit at, not {self.settings.get("profit_points")!r}')
        if 'most_cycles' in self.settings:
            cycles = self._whole('most_cycles')
            if cycles is None or cycles < 1:
                problems.append(f'most_cycles must be a whole number of at least 1, not {self.settings.get("most_cycles")!r}')
        return problems

    def _positive(self, name):
        """One setting as a number above zero.

        Args:
            name (str): The setting's name.

        Returns:
            decimal.Decimal | None: The number, or None when it is missing or not a number above zero.
        """
        value = self.settings.get(name)
        if value is None or isinstance(value, bool):
            return None
        try:
            number = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            return None
        if not number.is_finite() or number <= 0:
            return None
        return number

    def _whole(self, name):
        """One setting as a whole number.

        Args:
            name (str): The setting's name.

        Returns:
            int | None: The number, or None when it is missing or not a whole number.
        """
        value = self.settings.get(name)
        if value is None or isinstance(value, bool):
            return None
        try:
            number = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            return None
        if not number.is_finite() or number != number.to_integral_value():
            return None
        return int(number)

    def ladder(self):
        """The ladder the rungs are laid out by.

        Returns:
            LadderExecution: The ladder.
        """
        return LadderExecution(self._positive('from_price'), self._positive('to_price'), self._whole('steps'))

    def needs_prices(self):
        """Whether this part needs the instrument's tick size, which it does, to round its rungs and profit-takers.

        Returns:
            bool: True.
        """
        return True

    def prepared_own_memory(self, plan_order):
        """Checks, when the plan is placed, that the quantity covers one unit per rung.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            dict: Nothing to remember yet, so an empty dict.

        Raises:
            RefusedRequestError: With HTTP 400 when the quantity is smaller than the number of rungs.
        """
        steps = self._whole('steps')
        quantity = plan_order.read_order(self.context(plan_order).body).quantity
        if quantity < steps:
            raise RefusedRequestError.refusal(
                f'a ladder of {steps} steps needs a quantity of at least {steps}, not {quantity}',
                400,
            )
        return {}

    def start(self, plan_order, target, started_at, quotes, now=None):
        """Places every rung and remembers which broker order is which rung.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int | None): Unused, since the ladder's quantity is the body's.
            started_at (float | None): When the engine took the intent, or None.
            quotes (dict): Unused.
            now (float | None): Unused.

        Returns:
            list: One `(path, answer, status)` per rung placed.
        """
        del target, quotes, now
        context = self.context(plan_order)
        side = plan_order.read_order(context.body).transaction_type
        ladder = self.ladder()
        prices = ladder.rung_prices(context, side)
        quantities = ladder.quantities(plan_order.read_order(context.body).quantity)
        record = plan_order.part_record(self.path)
        record['state'] = 'working'
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} ladder is working')
        rungs = []
        rung_of_leg = {}
        placed = []
        for index in range(len(prices)):
            rungs.append({
                'price': str(prices[index]),
                'quantity': quantities[index],
                'cycles': 0,
            })
            body, status, leg_id = self.place_order(plan_order, self.limit_order(plan_order, side, prices[index], quantities[index]), started_at)
            rung_of_leg[leg_id] = index
            placed.append((self.path, body, status))
        self.remember(
            plan_order,
            {
                'rungs': rungs,
                'rung_of_leg': rung_of_leg,
                'handled': [],
            },
            f'the plan\'s {self.path} ladder placed {len(rungs)} rungs',
        )
        return placed

    def settle(self, plan_order):
        """Sends a profit-taker for every rung that has filled, places a rung again once its profit-taker has filled, and is done once every order has finished; once stopped, it places nothing more.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            list: One `(path, answer, status)` per order placed.
        """
        record = plan_order.part_record(self.path)
        if record.get('state') != 'working':
            return []
        if self.is_stopped(plan_order):
            self.finish_when_done(plan_order)
            return []
        context = self.context(plan_order)
        side = plan_order.read_order(context.body).transaction_type
        placed = []
        for leg in self.own_legs(plan_order.parent):
            memory = self.own_memory(plan_order)
            rung_index = (memory.get('rung_of_leg') or {}).get(leg.leg_id)
            if leg.state != 'filled' or rung_index is None or leg.leg_id in memory.get('handled', []):
                continue
            memory['handled'] = list(memory.get('handled', [])) + [
                leg.leg_id,
            ]
            rungs = [dict(rung) for rung in memory['rungs']]
            rung = rungs[rung_index]
            rung_price = decimal.Decimal(rung['price'])
            if leg.transaction_type == side:
                points = self._positive('profit_points')
                target_side = OPPOSITE_SIDES[side]
                target = rung_price + points if side == 'BUY' else rung_price - points
                rounded = MarketView(None, context.tick_size()).rounded(target, target_side)
                if rounded is not None:
                    target = rounded
                order = self.limit_order(plan_order, target_side, target, rung['quantity'])
                message = f'rung {rung_index + 1} filled at {rung_price}, so its profit is taken at {target}'
            else:
                most_cycles = self._whole('most_cycles')
                if most_cycles is not None and rung['cycles'] >= most_cycles:
                    self.remember(plan_order, memory, f'rung {rung_index + 1} has cycled {rung["cycles"]} times, which is its limit')
                    continue
                rung['cycles'] = rung['cycles'] + 1
                memory['rungs'] = rungs
                order = self.limit_order(plan_order, side, rung_price, rung['quantity'])
                message = f'the profit on rung {rung_index + 1} was taken, so the rung is placed again at {rung_price}'
            self.remember(plan_order, memory, message)
            body, status, leg_id = self.place_order(plan_order, order, None)
            memory = self.own_memory(plan_order)
            rung_of_leg = dict(memory.get('rung_of_leg') or {})
            rung_of_leg[leg_id] = rung_index
            memory['rung_of_leg'] = rung_of_leg
            self.remember(plan_order, memory, f'the plan\'s {self.path} order {leg_id} belongs to rung {rung_index + 1}')
            placed.append((self.path, body, status))
        self.finish_when_done(plan_order)
        return placed
