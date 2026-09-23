"""An order written down now and sent when a price reaches a level."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder

DIRECTIONS = (
    'at_or_above',
    'at_or_below',
)
OPPOSITE_SIDES = {
    'BUY': 'SELL',
    'SELL': 'BUY',
}


class PriceTrigger(SyntheticOrder):
    """What every order that waits for a price rather than for a fill has in common.

    A native stop does this at the exchange, and is better at it in every way but one: it can only watch its own instrument's last traded price, and it can only fire in the direction that runs away from a resting position. Those two limits are why this class exists. Everything here fires in either direction, on any instrument, from whichever part of the quote the type chooses, at the price of dying with the engine.

    The shape is always the same. Nothing is sent when the caller asks. The parent is written down and answers `202 armed`, carrying the parent id the caller needs to find it later, and then every price tick asks one question: has the level been reached? The first tick that says yes sends the child order, and the parent stops watching.

    **It fires once.** `triggered_at` goes into the parent's parameters before the child is placed, and a parent that already has one is not asked again. Without that, a level that stays crossed — which is the normal case, since a price that fell through a level tends to stay below it — would send a child order on every tick for the rest of the day.

    A subclass says four things: which instrument to watch, which price out of that instrument's quote to compare, which way the comparison goes by default, and what order to send when it fires.

    Attributes:
        ARMED_MESSAGE (str): What the `202` answer says this parent is waiting for.
    """

    WANTS_PRICES = True
    ARMED_MESSAGE = 'the level is reached'

    def run(self, intent, started_at):
        """Records the order and waits, without sending anything.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when the level or the direction cannot be read, and 503 when the instrument has no agreed tick size.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        level = self.read_level()
        direction = self.direction(order.transaction_type)

        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.remember_tick_size(order)
        self.record_received()
        self.save()
        self.arm(order, started_at)
        return {
            'broker': None,
            'instrument_id': self.parent.instrument_id,
            'parent_id': self.parent.parent_order_id,
            'tag': self.parent.tag,
            'outcome': 'armed',
            'order_id': None,
            'trigger_level': str(level),
            'trigger_direction': direction,
            'status_message': (
                f'the order is recorded and will be placed when '
                f'{self.ARMED_MESSAGE}'
            ),
            'skipped': [],
        }, 202

    def arm(self, order, started_at):
        """Places whatever has to rest at a broker while the trigger waits.

        Nothing does, for most types: the whole point of an engine-side trigger is that nothing is visible until it fires. The hidden stop overrides this to leave a far-away native stop behind as a backstop.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            None: This method returns nothing.
        """

    def read_level(self):
        """The price this trigger is waiting for.

        Returns:
            decimal.Decimal: The level.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or is not a price above zero.
        """
        value = self.parent.parameters.get('trigger_price')
        if value is None:
            raise RefusedRequestError.refusal(
                'this order type waits for a price, so it needs trigger_price',
                400,
            )
        try:
            level = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'trigger_price must be a price, not {value!r}',
                400,
            )
        if level <= 0:
            raise RefusedRequestError.refusal(
                f'trigger_price must be above zero, not {level}',
                400,
            )
        return level

    def default_direction(self, transaction_type):
        """Which way the price has to move for this type to fire, when the caller did not say.

        A buy waits for the price to come down to the level and a sell waits for it to come up, which is the buy-the-dip meaning a market-if-touched order has. It is the opposite of a stop, and that is the whole reason these types cannot be native orders.

        Args:
            transaction_type (str): BUY or SELL.

        Returns:
            str: One of `DIRECTIONS`.
        """
        return 'at_or_below' if transaction_type == 'BUY' else 'at_or_above'

    def direction(self, transaction_type):
        """Which way the price has to move for this trigger to fire.

        Args:
            transaction_type (str): BUY or SELL.

        Returns:
            str: One of `DIRECTIONS`.

        Raises:
            RefusedRequestError: With HTTP 400 when the caller named something else.
        """
        named = self.parent.parameters.get('trigger_direction')
        if named is None:
            return self.default_direction(transaction_type)
        if named not in DIRECTIONS:
            raise RefusedRequestError.refusal(
                f'trigger_direction must be one of {", ".join(DIRECTIONS)}, '
                f'not {named!r}',
                400,
            )
        return named

    def watched_instrument(self):
        """Which instrument's quote this trigger reads.

        Returns:
            str: The instrument id, which is the traded one unless a subclass says otherwise.
        """
        return self.parent.instrument_id

    def watched_price(self, view):
        """Which price out of the watched instrument's quote the level is compared against.

        The last traded price, which is what a native stop watches too. A type that would rather watch the bid or the offer, so that one stray trade does not fire it, overrides this.

        Args:
            view (MarketView): The watched instrument's quote.

        Returns:
            decimal.Decimal | None: The price, or None when the quote does not carry it.
        """
        return view.last()

    def has_triggered(self, price, level, direction):
        """Whether the price has reached the level from the side that fires.

        Args:
            price (decimal.Decimal): The watched price.
            level (decimal.Decimal): The level.
            direction (str): One of `DIRECTIONS`.

        Returns:
            bool: True when the trigger should fire.
        """
        if direction == 'at_or_above':
            return price >= level
        return price <= level

    def child_order(self, order, view):
        """The order to send when the trigger fires.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            view (MarketView): The traded instrument's quote at the moment it fired.

        Returns:
            PlaceOrderRequest | None: The order to place, or None when it cannot be built from this quote.

        Raises:
            NotImplementedError: Always, because every type sends something different.
        """
        raise NotImplementedError(
            f'{type(self).__name__} must say what it places when it fires.'
        )

    def exit_side(self, transaction_type):
        """The side that closes a position the caller opened with `transaction_type`.

        Args:
            transaction_type (str): The side that opened the position.

        Returns:
            str: BUY or SELL.
        """
        return OPPOSITE_SIDES[transaction_type]

    def priced(self, order, price, transaction_type=None):
        """The caller's order, as a limit at a price this type worked out.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            price (decimal.Decimal): The limit price to send.
            transaction_type (str | None): The side to send, or None for the caller's own.

        Returns:
            PlaceOrderRequest: The order to place.
        """
        body = dict(self.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body['order_type'] = 'LIMIT'
        body['quantity'] = order.quantity
        body['transaction_type'] = transaction_type or order.transaction_type
        body['price'] = str(price)
        return self.read_order(body)

    def on_price_tick(self, quotes, now):
        """Fires the child order on the first tick where the level has been reached.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the child order was placed on this tick.
        """
        if self.parent.parameters.get('triggered_at') is not None:
            return False
        order = self.read_order(self.parent.body)
        watched = self.view(quotes, self.watched_instrument())
        price = self.watched_price(watched)
        if price is None:
            return False
        level = self.read_level()
        if not self.has_triggered(
            price,
            level,
            self.direction(order.transaction_type),
        ):
            return False
        traded = self.view(quotes)
        child = self.child_order(order, traded)
        if child is None:
            return False
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['triggered_at'] = now
        self.parent.parameters['triggered_price'] = str(price)
        self.save()
        return self.fire(child, price, level)

    def state_after_firing(self, outcome):
        """What the parent becomes once the child order has been sent.

        A parent that was already `protecting` stays there. That is the hidden stop with a backstop: it has been guarding a position since the moment it was armed, and firing does not stop it guarding one — it is now doing so with an exit rather than a resting stop, and it finishes when that exit fills. Moving it back to `working` would be a state machine running backwards, and `protecting` is not allowed to become `working` anyway.

        Args:
            outcome (str | None): What the broker said, as `place_leg` read it.

        Returns:
            str: The parent state to record.
        """
        state = {
            'accepted': 'working',
            'rejected': 'rejected',
        }.get(outcome, 'failed')
        if state == 'working' and self.parent.state == 'protecting':
            return 'protecting'
        return state

    def fire(self, child, price, level):
        """Sends the child order and records what the parent became.

        Args:
            child (PlaceOrderRequest): The order to place.
            price (decimal.Decimal): The watched price that fired it.
            level (decimal.Decimal): The level it reached.

        Returns:
            bool: True, because the trigger fired whatever the broker then said.
        """
        body, _, _ = self.place_leg(
            'entry',
            child,
            None,
            self.chosen_broker(),
        )
        outcome = body.get('outcome')
        state = self.state_after_firing(outcome)
        self.record_state(
            state,
            f'{price} reached the trigger at {level}; '
            f'{body.get("status_message") or outcome}',
        )
        self.save()
        return True
