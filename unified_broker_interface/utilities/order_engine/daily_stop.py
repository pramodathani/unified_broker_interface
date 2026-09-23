"""A stop that is placed fresh at the exchange every morning, for a position held overnight."""

import datetime
import decimal
import time

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder
from unified_broker_interface.utilities.order_engine.utilities import moments

DEFAULT_ARM_AT = '09:20'
DEFAULT_BUFFER_TICKS = 2
DEFAULT_DAYS = 30
MOST_DAYS = 365
# India keeps no daylight saving, so a day is always exactly this many seconds and the expiry can be
# arithmetic on the same clock the tick reads rather than a calendar calculation on another one.
SECONDS_IN_A_DAY = 86400
OPPOSITE_SIDES = {
    'BUY': 'SELL',
    'SELL': 'BUY',
}


class DailyStop(SyntheticOrder):
    """Places a native stop each morning for a position carried overnight, and replaces it the next day.

    A native stop dies at the close, so a position held for a week needs a new one every morning. Doing that by hand is five chances to forget, on the mornings that matter most.

    `transaction_type` is the side that opened the position, as it is for every type that protects one, so the stop this places is the opposite.

    **It is not armed at the opening bell.** The first minutes of a session are the pre-open auction settling, and a stop placed into that can be triggered by a price that lasts seconds. `arm_at` defaults to 09:20, five minutes after the open, by which time the last traded price means something.

    **If the market has already gapped through the stop, no stop is placed.** A stop-loss limit whose trigger is on the wrong side of the last price is either refused outright by the broker or fires the instant it is accepted, at whatever the gap left behind. Neither is what anybody wants from a stop they set the night before. So the position is exited instead, with a limit priced past the touch, which at least chooses the price rather than taking it. That is the case this type exists to get right, and it is the one that happens on the worst mornings.

    `valid_days` is how many days it keeps re-arming, after which it stops — because a stop still being placed every morning for a position closed weeks ago is worse than no stop.
    """

    SYNTHETIC_TYPE = 'daily_stop'
    WANTS_CLOCK = True
    CARRIES_OVERNIGHT = True

    def read_stop_prices(self):
        """The stop's trigger and limit.

        Returns:
            tuple: The trigger and limit as `decimal.Decimal`.

        Raises:
            RefusedRequestError: With HTTP 400 when either is missing or is not a price above zero.
        """
        prices = []
        for name in ('stop_price', 'stop_limit_price'):
            value = self.parent.parameters.get(name)
            if value is None:
                raise RefusedRequestError.refusal(
                    'a daily stop needs stop_price and stop_limit_price: a '
                    'stop-limit whose limit sits at its trigger will not fill '
                    'when the price runs through it, which is what a stop is '
                    'for',
                    400,
                )
            try:
                price = decimal.Decimal(str(value))
            except (decimal.InvalidOperation, TypeError, ValueError):
                raise RefusedRequestError.refusal(
                    f'{name} must be a price, not {value!r}',
                    400,
                )
            if price <= 0:
                raise RefusedRequestError.refusal(
                    f'{name} must be above zero, not {price}',
                    400,
                )
            prices.append(price)
        return prices[0], prices[1]

    def read_valid_days(self):
        """How many mornings this keeps re-arming.

        Returns:
            int: The number of days.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a whole number in range.
        """
        value = self.parent.parameters.get('valid_days', DEFAULT_DAYS)
        try:
            days = int(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'valid_days must be a whole number of days, not {value!r}',
                400,
            )
        if days < 1 or days > MOST_DAYS:
            raise RefusedRequestError.refusal(
                f'valid_days must be between 1 and {MOST_DAYS}, not {days}',
                400,
            )
        return days

    def arm_at(self):
        """The time of day the stop is placed at.

        Returns:
            str: The time, as `HH:MM`.
        """
        return self.parent.parameters.get('arm_at') or DEFAULT_ARM_AT

    def exit_side(self, transaction_type):
        """The side that closes the position.

        Args:
            transaction_type (str): The side that opened it.

        Returns:
            str: BUY or SELL.
        """
        return OPPOSITE_SIDES[transaction_type]

    def run(self, intent, started_at):
        """Records the stop and waits for the next morning, without sending anything.

        Nothing is placed now, even during a session. A daily stop is a statement about tomorrow and every morning after it; somebody who wants a stop resting this afternoon is asking for an ordinary stop-loss limit order and should send one.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 for a bad stop or validity, and 503 when the instrument has no agreed tick size.
        """
        order = self.read_order(self.parent.body)
        trigger, limit = self.read_stop_prices()
        days = self.read_valid_days()

        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.remember_tick_size(order)
        self.record_received()
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['expires_at'] = (
            time.time() + days * SECONDS_IN_A_DAY
        )
        self.parent.parameters['armed_on'] = None
        self.save()
        return {
            'broker': None,
            'instrument_id': self.parent.instrument_id,
            'parent_id': self.parent.parent_order_id,
            'tag': self.parent.tag,
            'outcome': 'scheduled',
            'order_id': None,
            'arm_at': self.arm_at(),
            'stop_price': str(trigger),
            'valid_days': days,
            'status_message': (
                f'a stop at {trigger} will be placed at {self.arm_at()} every '
                f'morning for the next {days} days'
            ),
            'skipped': [],
        }, 202

    def today_in_india(self, now):
        """Which date a moment falls on, in the exchange's own timezone.

        Args:
            now (float): The Unix time.

        Returns:
            str: The date, as `YYYY-MM-DD`.
        """
        return datetime.datetime.fromtimestamp(
            now,
            moments.INDIA,
        ).date().isoformat()

    def due(self, now):
        """Whether it is time to arm today's stop.

        Args:
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the stop should be placed now.
        """
        if self.parent.parameters.get('armed_on') == self.today_in_india(now):
            return False
        when = datetime.datetime.fromtimestamp(now, moments.INDIA)
        hours, _, minutes = self.arm_at().partition(':')
        try:
            arm_at = when.replace(
                hour=int(hours),
                minute=int(minutes),
                second=0,
                microsecond=0,
            )
        except ValueError:
            return False
        return when >= arm_at

    def on_clock_tick(self, now):
        """Arms today's stop, or exits the position if the market has already gone past it.

        Args:
            now (float): The Unix time of the tick.

        Returns:
            bool: True when something was placed on this tick.
        """
        expires_at = self.parent.parameters.get('expires_at')
        if isinstance(expires_at, (int, float)) and now >= expires_at:
            if not self.parent.is_terminal():
                self.record_state(
                    'completed',
                    f'the stop was re-armed for {self.read_valid_days()} days '
                    'and has now finished',
                )
                self.save()
                return True
            return False
        if not self.due(now):
            return False

        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['armed_on'] = self.today_in_india(now)
        self.save()

        order = self.read_order(self.parent.body)
        trigger, limit = self.read_stop_prices()
        side = self.exit_side(order.transaction_type)
        _, quote, _ = self.placement.market_context(
            self.parent.instrument_id,
            True,
            False,
        )
        view = self.view({self.parent.instrument_id: quote})
        last = view.last()
        if last is None:
            return False
        if self.gapped_through(last, trigger, side):
            return self.exit_now(order, side, view, last, trigger)
        return self.arm_stop(order, side, trigger, limit)

    def gapped_through(self, last, trigger, side):
        """Whether the market has already passed the level the stop was meant to catch.

        Args:
            last (decimal.Decimal): The last traded price.
            trigger (decimal.Decimal): The stop's trigger.
            side (str): The exit's side.

        Returns:
            bool: True when a stop placed now would fire at once.
        """
        if side == 'SELL':
            return last <= trigger
        return last >= trigger

    def arm_stop(self, order, side, trigger, limit):
        """Places today's stop at the broker.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            side (str): The exit's side.
            trigger (decimal.Decimal): The stop's trigger.
            limit (decimal.Decimal): The stop's limit.

        Returns:
            bool: True, because a stop was sent whatever the broker then said.
        """
        body = dict(self.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body.pop('synthetic', None)
        body['order_type'] = 'SL'
        body['quantity'] = order.quantity
        body['transaction_type'] = side
        body['price'] = str(limit)
        body['trigger_price'] = str(trigger)
        answer, _, _ = self.place_leg(
            'stop',
            self.read_order(body),
            None,
            self.chosen_broker(),
        )
        if self.parent.state != 'protecting':
            self.record_state(
                'protecting' if answer.get('outcome') == 'accepted'
                else 'failed',
                f"today's stop is resting at {trigger}",
            )
        self.save()
        return True

    def exit_now(self, order, side, view, last, trigger):
        """Closes the position, because the market opened past where the stop would have been.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            side (str): The exit's side.
            view (MarketView): The live quote.
            last (decimal.Decimal): The last traded price.
            trigger (decimal.Decimal): The stop's trigger, for the message.

        Returns:
            bool: True when the exit was sent.
        """
        touch = view.opposite_touch(side)
        if touch is None:
            touch = last
        price = view.moved(touch, DEFAULT_BUFFER_TICKS, side, True)
        price = view.rounded(price, side)
        if price is None or price <= 0:
            return False
        body = dict(self.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body.pop('synthetic', None)
        body['order_type'] = 'LIMIT'
        body['quantity'] = order.quantity
        body['transaction_type'] = side
        body['price'] = str(price)
        self.place_leg(
            'close',
            self.read_order(body),
            None,
            self.chosen_broker(),
        )
        self.record_state(
            'completed',
            f'the market opened at {last}, already past the stop at '
            f'{trigger}, so the position was closed rather than a stop placed',
        )
        self.save()
        return True
