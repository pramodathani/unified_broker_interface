"""Buy limits below and sell limits above, each fill placing its opposite one step away."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder

MOST_LEVELS = 20
OPPOSITE_SIDES = {
    'BUY': 'SELL',
    'SELL': 'BUY',
}


class Grid(SyntheticOrder):
    """A ladder of buys below the market and sells above it, each rebuilding the other as it fills.

    A grid makes money from a market that goes nowhere. Put buy limits every five rupees below and sell limits every five rupees above; when a buy fills at 995, place a sell at 1000; when that fills, place a buy at 995 again. Each round trip keeps the step, and a market that oscillates all day pays it over and over.

    It is also the type in this package with the most direct way of going badly wrong, and the Atlas says so plainly: **a trending market keeps adding to the losing side.** In a market that falls all afternoon, every buy fills, every sell placed above it does not, and the grid quietly accumulates a large long position at prices that keep getting worse. Nothing about the mechanism notices, because from the inside it looks exactly like a market that is about to come back.

    `most_inventory` is the answer, and it is required rather than defaulted. Once the net position reaches it, every resting rung on the side that would make the position bigger is cancelled, and only the exits are left. The grid is then one-sided until the market comes back, which is the honest behaviour: it stops digging rather than pretending it can trade its way out.

    `levels` is how many orders go out on each side and `step_points` is the gap between them. `quantity` on the order is the size of each individual order, not of the whole grid, because the grid has no whole: it is a standing arrangement rather than an order for a quantity.
    """

    SYNTHETIC_TYPE = 'grid'

    def read_levels(self):
        """How many orders go out on each side.

        Returns:
            int: The count.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or out of range.
        """
        value = self.parent.parameters.get('levels')
        if value is None:
            raise RefusedRequestError.refusal(
                'a grid needs levels, how many orders go out on each side',
                400,
            )
        try:
            levels = int(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'levels must be a whole number, not {value!r}',
                400,
            )
        if levels < 1 or levels > MOST_LEVELS:
            raise RefusedRequestError.refusal(
                f'levels must be between 1 and {MOST_LEVELS}, not {levels}',
                400,
            )
        return levels

    def read_step(self):
        """The gap between one level and the next.

        Returns:
            decimal.Decimal: The step, in price.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or is not above zero.
        """
        value = self.parent.parameters.get('step_points')
        if value is None:
            raise RefusedRequestError.refusal(
                'a grid needs step_points, the gap between one level and the '
                'next',
                400,
            )
        try:
            step = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'step_points must be a number, not {value!r}',
                400,
            )
        if not step.is_finite() or step <= 0:
            raise RefusedRequestError.refusal(
                f'step_points must be above zero, not {step}',
                400,
            )
        return step

    def read_most_inventory(self):
        """The largest net position the grid may hold in either direction.

        Returns:
            int: The cap in units.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or is not a whole number above zero.
        """
        value = self.parent.parameters.get('most_inventory')
        if value is None:
            raise RefusedRequestError.refusal(
                'a grid needs most_inventory: a trending market fills one '
                'side over and over, and without a cap the position keeps '
                'growing at prices that keep getting worse',
                400,
            )
        try:
            most = int(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'most_inventory must be a whole number, not {value!r}',
                400,
            )
        if most < 1:
            raise RefusedRequestError.refusal(
                f'most_inventory must be at least one, not {most}',
                400,
            )
        return most

    def inventory(self):
        """The net position the grid's own fills have built, in units.

        Returns:
            int: Positive when long.
        """
        net = 0
        for leg in self.parent.legs:
            filled = leg.filled_quantity or 0
            if not filled:
                continue
            if leg.transaction_type == 'BUY':
                net = net + filled
            else:
                net = net - filled
        return net

    def adding_side(self):
        """Which side would make the position bigger rather than smaller.

        Returns:
            str | None: BUY when the grid is long, SELL when it is short, and None when it is flat.
        """
        net = self.inventory()
        if net > 0:
            return 'BUY'
        if net < 0:
            return 'SELL'
        return None

    def past_its_cap(self):
        """Whether the grid is holding as much as it was allowed to.

        Returns:
            bool: True when the net position has reached the cap in either direction.
        """
        return abs(self.inventory()) >= self.read_most_inventory()

    def stop_adding(self, side):
        """Cancels the rungs that would make the position bigger still.

        This is the whole of the inventory cap, and it took a rewrite to get right. The first version checked the cap before placing the replacement rung, which can never refuse anything: a filled buy is replaced by a sell, and a sell always makes a long position smaller. The orders that grow the position are the ones already resting further down the ladder, and cancelling those is the only thing that actually stops a falling market being bought all the way down.

        Args:
            side (str): BUY or SELL, whichever would add to the position.

        Returns:
            int: How many rungs were cancelled.
        """
        cancelled = 0
        for leg in list(self.parent.legs):
            if leg.role != 'rung' or leg.is_finished():
                continue
            if leg.transaction_type != side:
                continue
            if leg.broker_order_id is None:
                continue
            accepted = self.cancel_leg(
                leg,
                f'the grid is holding {self.inventory()}, which is its whole '
                f'allowance, so it stops adding to that side',
            )
            if accepted:
                cancelled = cancelled + 1
        return cancelled

    def level_order(self, order, side, price):
        """One order of the grid.

        Args:
            order (PlaceOrderRequest): The validated order, whose quantity is one level's size.
            side (str): BUY or SELL.
            price (decimal.Decimal): The price for this level.

        Returns:
            PlaceOrderRequest: The order to place.
        """
        body = dict(self.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body['order_type'] = 'LIMIT'
        body['quantity'] = order.quantity
        body['transaction_type'] = side
        body['price'] = str(price)
        return self.read_order(body)

    def run(self, intent, started_at):
        """Places the whole ladder, both sides, around the market as it is now.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 for a bad grid, and 503 when there is no tick size or no quote to build it around.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        levels = self.read_levels()
        step = self.read_step()
        self.read_most_inventory()

        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.remember_tick_size(order)
        _, quote, _ = self.placement.market_context(
            self.parent.instrument_id,
            True,
            False,
        )
        view = self.view({self.parent.instrument_id: quote})
        middle = view.last()
        if middle is None:
            raise RefusedRequestError.refusal(
                'a grid is built around where the market is and the live '
                'quote does not carry a last traded price yet',
                503,
                instrument_id=self.parent.instrument_id,
            )

        self.record_received()
        self.save()

        answers = []
        broker_name = None
        for index in range(1, levels + 1):
            for side in ('BUY', 'SELL'):
                if side == 'BUY':
                    price = view.rounded(middle - step * index, 'BUY')
                else:
                    price = view.rounded(middle + step * index, 'SELL')
                if price is None or price <= 0:
                    continue
                body, status, _ = self.place_leg(
                    'rung',
                    self.level_order(order, side, price),
                    started_at,
                    broker_name,
                )
                if broker_name is None:
                    broker_name = body.get('broker')
                answers.append((side, price, body, status))
        return self.settle(answers, broker_name, middle)

    def settle(self, answers, broker_name, middle):
        """Records what the ladder did and answers the waiting worker.

        Args:
            answers (list): One `(side, price, body, status)` per rung.
            broker_name (str | None): The broker every rung went to.
            middle (decimal.Decimal): The price the grid was built around.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        outcomes = [body.get('outcome') for _, _, body, _ in answers]
        if 'unknown' in outcomes:
            state = 'failed'
        elif 'accepted' in outcomes:
            state = 'working'
        else:
            state = 'rejected'
        self.record_state(state, f'the grid is set around {middle}')
        self.save()
        outcome = 'accepted'
        if 'unknown' in outcomes:
            outcome = 'unknown'
        elif 'accepted' not in outcomes:
            outcome = 'rejected'
        return {
            'broker': broker_name,
            'instrument_id': self.parent.instrument_id,
            'parent_id': self.parent.parent_order_id,
            'tag': self.parent.tag,
            'outcome': outcome,
            'centre_price': str(middle),
            'rungs': [
                {
                    'side': side,
                    'price': str(price),
                    'order_id': body.get('order_id'),
                    'outcome': body.get('outcome'),
                }
                for side, price, body, _ in answers
            ],
            'skipped': answers[0][2].get('skipped') if answers else [],
            'timing_ms': answers[0][2].get('timing_ms') if answers else {},
        }, max(status for _, _, _, status in answers) if answers else 200

    def on_leg_update(self, leg, changes):
        """Replaces a filled rung with its opposite, one step away.

        Args:
            leg (OrderLeg): The leg that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        if leg.role != 'rung' or leg.state != 'filled':
            return
        if leg.price is None:
            return
        order = self.concrete_order(self.read_order(self.parent.body))
        side = OPPOSITE_SIDES[leg.transaction_type]
        step = self.read_step()
        filled_at = decimal.Decimal(str(leg.price))
        price = filled_at + step if side == 'SELL' else filled_at - step
        if price > 0:
            self.place_leg(
                'rung',
                self.level_order(order, side, price),
                None,
                self.chosen_broker(),
            )
        if self.past_its_cap():
            adding = self.adding_side()
            if adding is not None:
                self.stop_adding(adding)
        self.save()
