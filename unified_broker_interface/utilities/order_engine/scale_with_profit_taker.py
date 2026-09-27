"""A ladder whose every filled rung gets its own profit-taker, and is placed again once that profit is taken."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.ladder import Ladder

OPPOSITE_SIDES = {
    'BUY': 'SELL',
    'SELL': 'BUY',
}


class ScaleWithProfitTaker(Ladder):
    """A ladder that books profit rung by rung (the Atlas's G15, Interactive Brokers' ScaleTrader).

    The rungs are placed as a `ladder` places them, so a buy adds size at each step the market falls. When a rung has completely filled, a profit-taking limit for the same quantity goes out `profit_points` better: a sell above a filled buy, a buy below a filled sell. When that profit-taker fills, the rung is placed again at its own price, and the cycle repeats. Profit is therefore booked per rung, as a grid does, but each profit-taker belongs to one rung.

    **The size is capped by construction.** A rung is placed again only after its profit-taker has closed it, so the position never exceeds the ladder's own quantity. `most_cycles` limits how many times each rung is placed again, and without it a rung cycles until the parent is cancelled.

    A rung that only partly fills waits for the rest before its profit-taker goes out, so each profit-taker always matches a whole rung.
    """

    SYNTHETIC_TYPE = 'scale_with_profit_taker'
    FINISHES_WITH_LEGS = False

    def read_profit_points(self):
        """How far past a filled rung its profit-taker sits.

        Returns:
            decimal.Decimal: The distance, in price.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or is not a number above zero.
        """
        value = self.parent.parameters.get('profit_points')
        try:
            points = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            points = None
        if value is None or points is None or not points.is_finite() or points <= 0:
            raise RefusedRequestError.refusal(
                'a scale with profit-taker needs profit_points, the distance '
                f'above zero to take each rung\'s profit at, not {value!r}',
                400,
            )
        return points

    def read_most_cycles(self):
        """How many times each rung may be placed again, or None for no limit.

        Returns:
            int | None: The limit.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a whole number of at least 1.
        """
        value = self.parent.parameters.get('most_cycles')
        if value is None:
            return None
        try:
            cycles = int(value)
        except (TypeError, ValueError):
            cycles = 0
        if cycles < 1:
            raise RefusedRequestError.refusal(
                f'most_cycles must be a whole number of at least 1, not {value!r}',
                400,
            )
        return cycles

    def run(self, intent, started_at):
        """Places the ladder and remembers which leg is which rung.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For a bad range, step count, profit distance or cycle limit, and for an order answered without calling a broker.
        """
        self.read_profit_points()
        self.read_most_cycles()
        order = self.read_order(self.parent.body)
        if not order.dry_run:
            self.remember_tick_size(order)
        body, status = super().run(intent, started_at)
        if order.dry_run:
            return body, status
        rungs = []
        rung_of_leg = {}
        for leg in self.parent.legs:
            if leg.role != 'slice':
                continue
            rung_of_leg[leg.leg_id] = len(rungs)
            rungs.append({
                'price': str(leg.price),
                'quantity': leg.quantity,
                'cycles': 0,
            })
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['rungs'] = rungs
        self.parent.parameters['rung_of_leg'] = rung_of_leg
        self.save()
        return body, status

    def limit_order(self, transaction_type, price, quantity):
        """A plain limit order on the parent's instrument.

        Args:
            transaction_type (str): BUY or SELL.
            price (decimal.Decimal): The price.
            quantity (int): The quantity, in units.

        Returns:
            PlaceOrderRequest: The order.
        """
        body = dict(self.parent.body)
        body.pop('synthetic', None)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body['order_type'] = 'LIMIT'
        body['transaction_type'] = transaction_type
        body['price'] = str(price)
        body['quantity'] = quantity
        return self.read_order(body)

    def remember_leg(self, leg_id, rung_index):
        """Records which rung a newly placed leg belongs to.

        Args:
            leg_id (str): The leg's id.
            rung_index (int): The rung.

        Returns:
            None: This method returns nothing.
        """
        rung_of_leg = dict(self.parent.parameters.get('rung_of_leg') or {})
        rung_of_leg[leg_id] = rung_index
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['rung_of_leg'] = rung_of_leg

    def on_leg_update(self, leg, changes):
        """Sends a profit-taker when a rung has filled, and places the rung again when its profit-taker has filled.

        Args:
            leg (OrderLeg): The leg that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        if leg.state != 'filled':
            return
        rung_index = (self.parent.parameters.get('rung_of_leg') or {}).get(leg.leg_id)
        if rung_index is None:
            return
        handled = set(self.parent.parameters.get('handled_legs') or [])
        if leg.leg_id in handled:
            return
        handled.add(leg.leg_id)
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['handled_legs'] = sorted(handled)
        rungs = [dict(rung) for rung in self.parent.parameters['rungs']]
        rung = rungs[rung_index]
        side = self.read_order(self.parent.body).transaction_type
        rung_price = decimal.Decimal(rung['price'])

        if leg.role == 'slice':
            points = self.read_profit_points()
            if side == 'BUY':
                target = rung_price + points
            else:
                target = rung_price - points
            target_side = OPPOSITE_SIDES[side]
            template = self.read_order(self.parent.body)
            target = template.rounded_to_tick(
                target,
                self.tick_size(),
                target_side,
            )
            order = self.limit_order(target_side, target, rung['quantity'])
            _, _, leg_id = self.place_leg('target', order, None, leg.broker)
            self.remember_leg(leg_id, rung_index)
            self.record_parameters(
                f'rung {rung_index + 1} filled at {rung_price}, so its profit '
                f'is taken at {target}'
            )
            self.save()
            return

        if leg.role != 'target':
            return
        most_cycles = self.read_most_cycles()
        if most_cycles is not None and rung['cycles'] >= most_cycles:
            self.record_parameters(
                f'rung {rung_index + 1} has cycled {rung["cycles"]} times, '
                'which is its limit'
            )
            self.save()
            return
        rung['cycles'] = rung['cycles'] + 1
        self.parent.parameters['rungs'] = rungs
        order = self.limit_order(side, rung_price, rung['quantity'])
        _, _, leg_id = self.place_leg('slice', order, None, leg.broker)
        self.remember_leg(leg_id, rung_index)
        self.record_parameters(
            f'the profit on rung {rung_index + 1} was taken, so the rung is '
            f'placed again at {rung_price}'
        )
        self.save()
