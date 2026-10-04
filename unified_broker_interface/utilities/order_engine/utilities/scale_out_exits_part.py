"""A plan order kept whole as a scale-out's exits: several targets taking a position off in tranches, and one stop that shrinks behind them."""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.whole_part import (
    WholePart,
)

OPPOSITE_SIDES = {
    'BUY': 'SELL',
    'SELL': 'BUY',
}
SETTINGS = (
    'stop_price',
    'stop_limit_price',
    'target_prices',
    'breakeven_after',
)


class ScaleOutExitsPart(WholePart):
    """The exits of a scale-out in a plan, with the rules of today's scale-out type; the `scale_out` preset puts them under a Then join after the entry.

    When the entry first fills, a stop-limit at `stop_price` and `stop_limit_price` goes out for everything filled, with a limit at each of `target_prices` taking an even share of it, the first targets taking the remainder; with fewer units than targets, the last target takes it all. The targets are tranches of one position, so a target filling shrinks only the stop, which always covers what is still held, and the stop growing as the entry fills further leaves the targets alone. When the stop fills, the targets shrink from the furthest first. Once `breakeven_after` targets (default 1) have filled anything, the stop moves to the entry's average price.

    The stop is told from the targets by its leg id, kept in the part's memory. It must be a Then join's child, since it protects what the first plan opened.

    Attributes:
        NEEDS_THEN (bool): True, since the exits protect what a Then join's first plan filled.
    """

    NEEDS_THEN = True

    def _price(self, value):
        """A price above zero, or None.

        Args:
            value (object): The value.

        Returns:
            decimal.Decimal | None: The price, or None when it is not a number above zero.
        """
        if value is None or isinstance(value, bool):
            return None
        try:
            price = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            return None
        if not price.is_finite() or price <= 0:
            return None
        return price

    def settings_problems(self):
        """Every problem with the settings, in today's words.

        Returns:
            list: One message (str) per problem.
        """
        problems = []
        for name in self.settings:
            if name not in SETTINGS:
                problems.append(f'the scale_out preset takes {", ".join(SETTINGS)}, not {name!r}')
        listed = self.settings.get('target_prices')
        if not isinstance(listed, list) or len(listed) < 2:
            problems.append('a scale_out needs target_prices, a list of at least two prices to take the position off at')
        else:
            for position, value in enumerate(listed):
                if self._price(value) is None:
                    problems.append(f'target_prices[{position}] must be a price above zero, not {value!r}')
        if self._price(self.settings.get('stop_price')) is None or self._price(self.settings.get('stop_limit_price')) is None:
            problems.append('a scale_out needs stop_price and stop_limit_price: the stop is what covers whatever has not been taken off yet')
        breakeven_after = self.settings.get('breakeven_after', 1)
        if isinstance(breakeven_after, bool) or not isinstance(breakeven_after, int) or breakeven_after < 1:
            problems.append(f'breakeven_after must be a whole number of at least 1, not {breakeven_after!r}')
        return problems

    def tranches(self, filled, count):
        """How much each target takes, as evenly as whole units allow, the first targets taking the remainder.

        Args:
            filled (int): The whole position.
            count (int): How many targets share it.

        Returns:
            list: One quantity per target.
        """
        each = filled // count
        remainder = filled - each * count
        quantities = []
        for index in range(count):
            if index < remainder:
                quantities.append(each + 1)
            else:
                quantities.append(each)
        return quantities

    def stop_order(self, plan_order, side, quantity):
        """The stop-limit that covers the position.

        Args:
            plan_order (PlanOrder): The plan order.
            side (str): BUY or SELL, against the position.
            quantity (int): The quantity.

        Returns:
            PlaceOrderRequest: The order.
        """
        body = dict(self.context(plan_order).body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        if not self.keeps_tag and 'tag' not in self.overrides:
            body.pop('tag', None)
        body['order_type'] = 'SL'
        body['transaction_type'] = side
        body['quantity'] = quantity
        body['price'] = str(self._price(self.settings['stop_limit_price']))
        body['trigger_price'] = str(self._price(self.settings['stop_price']))
        return plan_order.concrete_order(plan_order.read_order(body))

    def start(self, plan_order, target, started_at, quotes, now=None):
        """Places the stop for everything the entry has filled, and the targets that share it.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int): How much the entry has filled.
            started_at (float | None): Unused, since the exits follow a fill.
            quotes (dict): Unused.
            now (float | None): Unused.

        Returns:
            list: One `(path, answer, status)` per exit placed.
        """
        del started_at, quotes, now
        record = plan_order.part_record(self.path)
        record['state'] = 'working'
        record['target'] = target
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} exits protect the {target} the entry filled')
        side = OPPOSITE_SIDES[self._opening_side(plan_order)]
        prices = []
        for value in self.settings['target_prices']:
            prices.append(self._price(value))
        if target < len(prices):
            prices = prices[-1:]
        placed = []
        body, status, stop_id = self.place_order(plan_order, self.stop_order(plan_order, side, target), None)
        placed.append((self.path, body, status))
        quantities = self.tranches(target, len(prices))
        for index in range(len(prices)):
            body, status, _ = self.place_order(plan_order, self.limit_order(plan_order, side, prices[index], quantities[index]), None)
            placed.append((self.path, body, status))
        self.remember(
            plan_order,
            {
                'stop': stop_id,
                'at_breakeven': False,
            },
            f'the plan\'s {self.path} stop is {stop_id}',
        )
        return placed

    def stop_leg(self, plan_order):
        """The stop's broker order.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            OrderLeg | None: The leg, or None before it is placed.
        """
        stop_id = self.own_memory(plan_order).get('stop')
        for leg in self.own_legs(plan_order.parent):
            if leg.leg_id == stop_id:
                return leg
        return None

    def target_legs(self, plan_order):
        """The targets' broker orders, nearest first.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            list: The legs.
        """
        stop_id = self.own_memory(plan_order).get('stop')
        found = []
        for leg in self.own_legs(plan_order.parent):
            if leg.leg_id != stop_id:
                found.append(leg)
        return found

    def taken_by_targets(self, plan_order):
        """How much the targets have taken off.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            int: The quantity.
        """
        total = 0
        for leg in self.target_legs(plan_order):
            total = total + (leg.filled_quantity or 0)
        return total

    def fit_stop(self, plan_order):
        """Sizes the stop to what is still held, the entry's fill less what the targets took, and cancels it once nothing is.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            None: This method returns nothing.
        """
        stop = self.stop_leg(plan_order)
        if stop is None or stop.is_finished() or not stop.broker_order_id:
            return
        target = plan_order.part_record(self.path).get('target') or 0
        wanted = target - self.taken_by_targets(plan_order)
        if wanted == stop.quantity:
            return
        if wanted <= (stop.filled_quantity or 0):
            self.cancel_once(plan_order, stop, 'the targets have taken the whole position off, so the stop has nothing left to cover')
            return
        plan_order.reduce_leg(stop, wanted, f'the entry has filled {target} and the targets have taken {self.taken_by_targets(plan_order)} off, so the stop covers {wanted}')

    def fit_targets(self, plan_order):
        """Shrinks the resting targets, furthest first, to what the stop has left, once the stop has filled anything.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            None: This method returns nothing.
        """
        stop = self.stop_leg(plan_order)
        if stop is None or not stop.filled_quantity:
            return
        target = plan_order.part_record(self.path).get('target') or 0
        left = target - self.taken_by_targets(plan_order) - stop.filled_quantity
        resting = []
        for leg in self.target_legs(plan_order):
            if not leg.is_finished() and leg.broker_order_id:
                resting.append(leg)
        unfilled = 0
        for leg in resting:
            unfilled = unfilled + (leg.quantity or 0) - (leg.filled_quantity or 0)
        excess = unfilled - max(left, 0)
        for leg in reversed(resting):
            if excess <= 0:
                break
            open_quantity = (leg.quantity or 0) - (leg.filled_quantity or 0)
            cut = min(excess, open_quantity)
            excess = excess - cut
            if cut == open_quantity:
                self.cancel_once(plan_order, leg, f'the stop filled {stop.filled_quantity}, so this target has nothing left to take')
            else:
                plan_order.reduce_leg(leg, (leg.quantity or 0) - cut, f'the stop filled {stop.filled_quantity}, so this target takes less')

    def entry_average_price(self, plan_order):
        """The average price the entry filled at, across its broker orders.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            decimal.Decimal | None: The price, or None before any fill carries one.
        """
        quantity = decimal.Decimal(0)
        value = decimal.Decimal(0)
        for leg in plan_order.parent.legs:
            if leg.role in self.opened_by and leg.filled_quantity and leg.average_price:
                filled = decimal.Decimal(leg.filled_quantity)
                quantity = quantity + filled
                value = value + filled * decimal.Decimal(str(leg.average_price))
        if quantity == 0:
            return None
        return value / quantity

    def move_to_breakeven(self, plan_order):
        """Moves the stop to the entry's average price once enough targets have filled, once.

        An average over several fills often falls between ticks, so the price is rounded to the tick on the stop's passive side: up for a sell stop protecting a long and down for a buy stop protecting a short, which keeps the trade unable to lose.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            None: This method returns nothing.
        """
        memory = self.own_memory(plan_order)
        if memory.get('at_breakeven'):
            return
        wanted = self.settings.get('breakeven_after', 1)
        filled_targets = 0
        for leg in self.target_legs(plan_order):
            if (leg.filled_quantity or 0) > 0:
                filled_targets = filled_targets + 1
        if filled_targets < wanted:
            return
        price = self.entry_average_price(plan_order)
        stop = self.stop_leg(plan_order)
        if price is None or stop is None or stop.is_finished():
            return
        tick_size = self.context(plan_order).tick_size()
        if tick_size:
            rounded = MarketView(None, tick_size).rounded(price, stop.transaction_type)
            if rounded is not None:
                price = rounded
        if plan_order.reprice_leg(stop, price, price, f'{wanted} target(s) have filled, so the stop moves to the entry price and the trade can no longer lose'):
            memory['at_breakeven'] = True
            self.remember(plan_order, memory, f'the plan\'s {self.path} stop is at the entry price')

    def set_target(self, plan_order, target):
        """Follows the entry's fills: the stop grows with them, and the targets stay as they were sized.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int): How much the entry has filled.

        Returns:
            None: This method returns nothing.
        """
        record = plan_order.part_record(self.path)
        if record.get('state') != 'working' or record.get('target') == target:
            return
        record['target'] = target
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} exits protect the {target} the entry filled')
        self.fit_stop(plan_order)

    def settle(self, plan_order):
        """Shrinks the stop by what the targets took, the targets by what the stop took, moves the stop to breakeven, and is done once every exit has finished.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            list: Nothing is placed while settling, so an empty list.
        """
        if plan_order.part_record(self.path).get('state') != 'working':
            return []
        self.fit_stop(plan_order)
        self.fit_targets(plan_order)
        self.move_to_breakeven(plan_order)
        self.finish_when_done(plan_order)
        return []
