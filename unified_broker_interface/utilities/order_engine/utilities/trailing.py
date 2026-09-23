"""A native stop whose trigger follows the market in one direction and never goes back."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder

HUNDRED = decimal.Decimal('100')
OPPOSITE_SIDES = {
    'BUY': 'SELL',
    'SELL': 'BUY',
}
DEFAULT_STEP_TICKS = 1


class TrailingOrder(SyntheticOrder):
    """A stop-loss limit at the broker, moved towards the market as the market moves away from it.

    Both trailing types are this one mechanism, and which one you get is decided entirely by which side the stop is on.

    A **sell** stop sits below the market. It exists either to protect a long position or to enter a short on a breakdown, and either way it ratchets *upwards*: the engine remembers the highest price seen, and the trigger follows it at a fixed distance. A **buy** stop sits above the market, protects a short or enters a long on a rebound, and ratchets *downwards* behind the lowest price seen.

    The watermark is the whole state. It only ever moves in the favourable direction, so the trigger only ever moves in the favourable direction, and a market that gives back some of its move leaves the stop where it was. That is what "trailing" means and it is the part that is easy to get subtly wrong: a stop that follows the price both ways is not a trailing stop, it is a stop that never fires.

    **The stop stays at the broker.** The alternative — remembering the level here and firing a marketable limit when the price crosses it — sends no modify traffic at all, and gives up the one thing a native stop has: it works while this process does not. Keeping it resting costs a `modify` each time the trigger ratchets, which is what `step_ticks` and the engine's re-pricing throttle are for.

    The distance comes from `trail_points` or `trail_percent`, one of the two. A percentage is measured against the watermark, so it widens as the trade goes your way, which is usually what somebody asking for a percentage means.

    `stop_limit_offset` is how far the limit sits past the trigger, and it is required. Stop-loss-market is gone from NSE options and from BSE entirely, so every stop here is a stop-limit, and a stop-limit whose limit sits at its trigger will not fill when the price runs through it — which is the one condition it exists for. NSE caps the gap at three per cent for cash-segment stocks above fifty rupees, so a very wide offset is refused by the exchange rather than by this.

    Attributes:
        ARMED_STATE (str): What the parent becomes once its stop is resting, which says whether this type is guarding a position or waiting to open one.
    """

    WANTS_PRICES = True
    ARMED_STATE = 'working'

    def leg_side(self, transaction_type):
        """Which way the stop itself trades.

        Args:
            transaction_type (str): The side the caller named.

        Returns:
            str: BUY or SELL.

        Raises:
            NotImplementedError: Always, because this is what the two trailing types disagree about.
        """
        raise NotImplementedError(
            f'{type(self).__name__} must say which side its stop is on.'
        )

    def read_trail(self, reference):
        """How far the trigger sits from the watermark.

        Args:
            reference (decimal.Decimal): The watermark, which a percentage is measured against.

        Returns:
            decimal.Decimal: The distance, in price.

        Raises:
            RefusedRequestError: With HTTP 400 when neither `trail_points` nor `trail_percent` is given, both are, or either is not above zero.
        """
        points = self.parent.parameters.get('trail_points')
        percent = self.parent.parameters.get('trail_percent')
        if points is None and percent is None:
            raise RefusedRequestError.refusal(
                'a trailing order needs trail_points or trail_percent to say '
                'how far behind the market its stop follows',
                400,
            )
        if points is not None and percent is not None:
            raise RefusedRequestError.refusal(
                'a trailing order takes trail_points or trail_percent, not '
                'both',
                400,
            )
        if points is not None:
            return self.positive(points, 'trail_points')
        return reference * self.positive(percent, 'trail_percent') / HUNDRED

    def read_limit_offset(self):
        """How far past the trigger the stop's limit price sits.

        Returns:
            decimal.Decimal: The offset, in price.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or is not above zero.
        """
        value = self.parent.parameters.get('stop_limit_offset')
        if value is None:
            raise RefusedRequestError.refusal(
                'a trailing order needs stop_limit_offset: a stop-limit whose '
                'limit sits at its trigger will not fill when the price runs '
                'through it, which is what a stop is for',
                400,
            )
        return self.positive(value, 'stop_limit_offset')

    def read_step_ticks(self):
        """How far the trigger has to be able to move before it is worth moving.

        Returns:
            int: The step in ticks.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a whole number of ticks above zero.
        """
        value = self.parent.parameters.get('step_ticks', DEFAULT_STEP_TICKS)
        try:
            ticks = int(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'step_ticks must be a whole number of ticks, not {value!r}',
                400,
            )
        if ticks < 1:
            raise RefusedRequestError.refusal(
                f'step_ticks must be at least one tick, not {ticks}',
                400,
            )
        return ticks

    def positive(self, value, name):
        """One of the caller's numbers, as a decimal above zero.

        Args:
            value (object): The value.
            name (str): Its name, for the message.

        Returns:
            decimal.Decimal: The number.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a number above zero.
        """
        try:
            number = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'{name} must be a number, not {value!r}',
                400,
            )
        if not number.is_finite() or number <= 0:
            raise RefusedRequestError.refusal(
                f'{name} must be above zero, not {number}',
                400,
            )
        return number

    def watermark(self):
        """The best price seen since this order was armed.

        Returns:
            decimal.Decimal | None: The watermark, or None before the first price was seen.
        """
        text = self.parent.parameters.get('watermark')
        if text is None:
            return None
        try:
            return decimal.Decimal(str(text))
        except decimal.InvalidOperation:
            return None

    def improves_watermark(self, price, watermark, leg_side):
        """Whether a price is further in the favourable direction than the watermark.

        A sell stop trails a rising market, so a higher price improves it. A buy stop trails a falling one, so a lower price does.

        Args:
            price (decimal.Decimal): The price just seen.
            watermark (decimal.Decimal | None): The best price so far.
            leg_side (str): BUY or SELL, the side the stop is on.

        Returns:
            bool: True when the watermark should move to this price.
        """
        if watermark is None:
            return True
        if leg_side == 'SELL':
            return price > watermark
        return price < watermark

    def trigger_from(self, watermark, leg_side):
        """Where the trigger belongs, given the watermark.

        Args:
            watermark (decimal.Decimal): The best price seen.
            leg_side (str): BUY or SELL, the side the stop is on.

        Returns:
            decimal.Decimal: The trigger price, before it is rounded to a tick.
        """
        trail = self.read_trail(watermark)
        if leg_side == 'SELL':
            return watermark - trail
        return watermark + trail

    def limit_from(self, trigger, leg_side):
        """Where the stop's limit belongs, given its trigger.

        The limit sits past the trigger in the direction the stop trades, so a sell stop's limit is below its trigger and a buy stop's above it. That is what lets a triggered stop actually fill rather than rest unfilled behind the move that triggered it.

        Args:
            trigger (decimal.Decimal): The trigger price.
            leg_side (str): BUY or SELL, the side the stop is on.

        Returns:
            decimal.Decimal: The limit price, before it is rounded to a tick.
        """
        offset = self.read_limit_offset()
        if leg_side == 'SELL':
            return trigger - offset
        return trigger + offset

    def improves_trigger(self, new_trigger, leg, tick_size):
        """Whether the trigger has earned a move, counting the step threshold.

        Args:
            new_trigger (decimal.Decimal): Where the trigger should be.
            leg (OrderLeg): The resting stop.
            tick_size (decimal.Decimal): The instrument's tick size.

        Returns:
            bool: True when the stop should be moved.
        """
        if leg.trigger_price is None:
            return True
        current = decimal.Decimal(str(leg.trigger_price))
        step = tick_size * self.read_step_ticks()
        if leg.transaction_type == 'SELL':
            return (new_trigger - current) >= step
        return (current - new_trigger) >= step

    def stop_order(self, order, trigger, limit, leg_side):
        """The stop-loss limit order to send.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            trigger (decimal.Decimal): The trigger price.
            limit (decimal.Decimal): The limit price.
            leg_side (str): BUY or SELL, the side the stop is on.

        Returns:
            PlaceOrderRequest: The order to place.
        """
        body = dict(self.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body['order_type'] = 'SL'
        body['quantity'] = order.quantity
        body['transaction_type'] = leg_side
        body['price'] = str(limit)
        body['trigger_price'] = str(trigger)
        return self.read_order(body)

    def run(self, intent, started_at):
        """Places the stop where the market is now, and starts trailing it.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 for a bad trail, offset or step, and 503 when there is no tick size or no quote to start from.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        leg_side = self.leg_side(order.transaction_type)
        self.read_limit_offset()
        self.read_step_ticks()

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
        start = view.last()
        if start is None:
            raise RefusedRequestError.refusal(
                'a trailing order measures its distance from the market and '
                'the live quote does not carry a last traded price yet',
                503,
                instrument_id=self.parent.instrument_id,
            )

        trigger = view.rounded(
            self.trigger_from(start, leg_side),
            leg_side,
        )
        limit = view.rounded(self.limit_from(trigger, leg_side), leg_side)
        self.record_received()
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['watermark'] = str(start)
        self.save()

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
        body['watermark'] = str(start)
        return body, status

    def on_price_tick(self, quotes, now):
        """Moves the watermark, and the stop with it, when the market has gone further.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the stop was moved.
        """
        leg = self.resting_stop()
        if leg is None:
            return False
        view = self.view(quotes)
        price = view.last()
        if price is None:
            return False
        tick_size = self.tick_size()
        watermark = self.watermark()
        if self.improves_watermark(price, watermark, leg.transaction_type):
            watermark = price
            self.parent.parameters = dict(self.parent.parameters)
            self.parent.parameters['watermark'] = str(watermark)
            self.save()
        if watermark is None:
            return False

        trigger = view.rounded(
            self.trigger_from(watermark, leg.transaction_type),
            leg.transaction_type,
        )
        if trigger is None:
            return False
        if not self.improves_trigger(trigger, leg, tick_size):
            return False
        limit = view.rounded(
            self.limit_from(trigger, leg.transaction_type),
            leg.transaction_type,
        )
        moved = self.reprice_leg(
            leg,
            limit,
            trigger,
            f'the market reached {watermark}, so the stop follows to {trigger}',
        )
        if moved:
            self.save()
        return moved

    def resting_stop(self):
        """The stop this order is trailing, while it can still fire.

        Returns:
            OrderLeg | None: The leg, or None when there is nothing resting.
        """
        for leg in self.parent.legs:
            if leg.role != 'stop' or leg.is_finished():
                continue
            if leg.broker_order_id is None:
                continue
            return leg
        return None
