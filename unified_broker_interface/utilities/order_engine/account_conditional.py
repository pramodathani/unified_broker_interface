"""An order sent, or cancelled, when the account itself reaches a level."""

import decimal
import json

import redis

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.price_trigger import (
    PriceTrigger,
)

FUNDS_KEY = 'unified:portfolio:funds'
ACCOUNT_FIELDS = (
    'available_balance',
    'day_pnl',
    'open_positions',
)
ACTIONS = (
    'place',
    'cancel',
)


class AccountConditional(PriceTrigger):
    """An order that waits on the account rather than on a price (the Atlas's G17, Interactive Brokers' conditions).

    The condition is one of three figures, compared with `account_level` in `trigger_direction`:

    - `available_balance`, the free margin across every broker, from `unified:portfolio:funds`;
    - `day_pnl`, realized plus unrealized profit across every broker, from the same document, as the daily loss lockout reads it;
    - `open_positions`, how many net positions are open, from `unified:portfolio:positions`.

    With `action: place`, the default, nothing is sent until the condition holds, which covers both "fire when" and "block until": send this entry once margin has freed up, or only once the book is flat. With `action: cancel`, the order is sent at once and cancelled when the condition holds, such as pulling a resting bid when the day's loss reaches a limit.

    The figures are read from Redis once a second, on the price ticker's clock, so a condition is noticed about a second after the combining scripts see it. `trigger_on` is refused, because it chooses between prices.
    """

    SYNTHETIC_TYPE = 'account_conditional'
    ARMED_MESSAGE = 'the account reaches the level'
    TAKES_TRIGGER_ON = False

    def read_field(self):
        """Which figure of the account the condition watches.

        Returns:
            str: One of `ACCOUNT_FIELDS`.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or unknown.
        """
        field = self.parent.parameters.get('account_field')
        if field not in ACCOUNT_FIELDS:
            raise RefusedRequestError.refusal(
                f'account_field must be one of {", ".join(ACCOUNT_FIELDS)}, '
                f'not {field!r}',
                400,
            )
        return field

    def read_action(self):
        """What happens when the condition holds.

        Returns:
            str: One of `ACTIONS`.

        Raises:
            RefusedRequestError: With HTTP 400 for another value.
        """
        action = self.parent.parameters.get('action') or 'place'
        if action not in ACTIONS:
            raise RefusedRequestError.refusal(
                f'action must be one of {", ".join(ACTIONS)}, not {action!r}',
                400,
            )
        return action

    def read_level(self):
        """The level the account figure is compared with.

        Returns:
            decimal.Decimal: The level, which may be negative for a loss.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or is not a number.
        """
        value = self.parent.parameters.get('account_level')
        try:
            level = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            level = None
        if value is None or level is None or not level.is_finite():
            raise RefusedRequestError.refusal(
                f'an account-conditional order needs account_level as a '
                f'number, not {value!r}',
                400,
            )
        return level

    def default_direction(self, transaction_type):
        """Refuses to guess which way the account figure has to move.

        A buy waiting for margin wants it to rise, and a cancel on a loss wants the profit to fall, so the side of the order says nothing about the direction.

        Args:
            transaction_type (str): BUY or SELL.

        Returns:
            str: Never returns.

        Raises:
            RefusedRequestError: With HTTP 400, always.
        """
        raise RefusedRequestError.refusal(
            'an account-conditional order needs trigger_direction, '
            'at_or_above or at_or_below',
            400,
        )

    def funds_figure(self, field):
        """One figure out of the combined funds document.

        Args:
            field (str): `available_balance` or `day_pnl`.

        Returns:
            decimal.Decimal | None: The figure, or None when the document cannot be read.
        """
        try:
            stored = self.placement.cache.get(FUNDS_KEY)
        except redis.RedisError as error:
            self.logger.warning(f'{FUNDS_KEY} could not be read: {error}')
            return None
        if not stored:
            return None
        try:
            document = json.loads(stored)
        except ValueError:
            return None
        if not isinstance(document, dict):
            return None
        if field == 'available_balance':
            summary = document.get('summary') or {}
            value = summary.get('available_balance')
            if not isinstance(value, (int, float)):
                return None
            return decimal.Decimal(str(value))
        profit_and_loss = document.get('pnl')
        if not isinstance(profit_and_loss, dict):
            return None
        total = decimal.Decimal(0)
        for name in ('realized', 'unrealized'):
            value = profit_and_loss.get(name)
            if isinstance(value, (int, float)):
                total = total + decimal.Decimal(str(value))
        return total

    def open_position_count(self):
        """How many net positions are open across every broker.

        Returns:
            decimal.Decimal | None: The count, or None when the positions cannot be read.
        """
        _, _, positions = self.placement.market_context(
            self.parent.instrument_id,
            False,
            True,
        )
        if not isinstance(positions, dict):
            return None
        count = 0
        for entry in positions.get('net') or []:
            if not isinstance(entry, dict):
                continue
            quantity = entry.get('quantity')
            if isinstance(quantity, (int, float)) and quantity != 0:
                count = count + 1
        return decimal.Decimal(count)

    def watched_price(self, view):
        """The account figure the condition watches, in place of a price.

        Args:
            view (MarketView): The quote, which is not used.

        Returns:
            decimal.Decimal | None: The figure, or None when it cannot be read.
        """
        field = self.read_field()
        if field == 'open_positions':
            return self.open_position_count()
        return self.funds_figure(field)

    def child_order(self, order, view):
        """The caller's own order, sent as it was asked for.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            view (MarketView): The quote, which is not used.

        Returns:
            PlaceOrderRequest: The order to place.
        """
        return self.concrete_order(order)

    def run(self, intent, started_at):
        """Arms the order, or, with `action: cancel`, sends it now and waits to cancel it.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when the field, level, direction or action cannot be read.
        """
        self.read_field()
        self.read_level()
        order = self.read_order(self.parent.body)
        self.direction(order.transaction_type)
        if self.read_action() == 'place':
            return super().run(intent, started_at)

        order = self.concrete_order(order)
        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)
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
        return body, status

    def on_price_tick(self, quotes, now):
        """Places the order when the condition holds, or cancels it with `action: cancel`.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when an order was placed or cancelled on this tick.
        """
        if self.read_action() == 'place':
            return super().on_price_tick(quotes, now)
        if self.parent.is_terminal():
            return False
        resting = None
        for leg in self.parent.legs:
            if leg.role == 'entry' and not leg.is_finished() and leg.broker_order_id:
                resting = leg
        if resting is None:
            return False
        figure = self.watched_price(None)
        if figure is None:
            return False
        order = self.read_order(self.parent.body)
        level = self.read_level()
        if not self.has_triggered(figure, level, self.direction(order.transaction_type)):
            return False
        reason = (
            f'{self.read_field()} reached {figure}, past the level of {level}, '
            'so the order is cancelled'
        )
        accepted = self.cancel_leg(resting, reason)
        if accepted:
            self.record_state('cancelled', reason)
        self.save()
        return True
