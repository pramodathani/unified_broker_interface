"""A trigger that waits across days, not just across a session."""

import time

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.limit_if_touched import (
    LimitIfTouched,
)

DEFAULT_DAYS = 30
MOST_DAYS = 365
# India keeps no daylight saving, so a day is always exactly this many seconds and the expiry can be
# arithmetic on the same clock the tick reads rather than a calendar calculation on another one.
SECONDS_IN_A_DAY = 86400


class GoodTillTriggered(LimitIfTouched):
    """A limit-if-touched order that survives the end of the day and keeps waiting.

    Every native order in India dies at the close. A stop-loss limit placed on Monday is gone on Tuesday morning, which is fine for an intraday trade and useless for a holding somebody means to keep for a month. That is the gap brokers fill with a product they call a good-till-triggered order, running it in their own systems and placing the real order when the trigger is crossed.

    This is the same thing run here instead, and the trade-offs are the same. It works while this engine is running and does nothing while it is not, where a broker's own version works whether or not anything of yours is up. Against that, it can watch whatever it likes and triggers in either direction, where a broker's is limited to what they chose to offer.

    **Neither version protects against a gap.** The trigger is checked against a live price, so an instrument that opens twenty per cent below the level fires immediately at the open and places its limit into a market that has already moved. That is inherent to the design rather than a limitation of this one: nothing that watches prices can act on a price that never traded.

    `valid_days` is how long it waits before giving up, thirty days by default and a year at most. An order that has not triggered by then is closed rather than left in the record for ever, because a trigger nobody has thought about for a year is more likely forgotten than intended.
    """

    SYNTHETIC_TYPE = 'gtt'
    CARRIES_OVERNIGHT = True
    ARMED_MESSAGE = 'the price touches the level, on any day before it expires'

    def read_valid_days(self):
        """How many days this order waits before giving up.

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

    def run(self, intent, started_at):
        """Records the trigger and when it expires, and sends nothing.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when the trigger, the limit price or the validity cannot be read.
        """
        days = self.read_valid_days()
        expires_at = time.time() + days * SECONDS_IN_A_DAY
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['expires_at'] = expires_at
        body, status = super().run(intent, started_at)
        if isinstance(body, dict):
            body['expires_at'] = expires_at
            body['valid_days'] = days
        return body, status

    def on_price_tick(self, quotes, now):
        """Fires when the level is touched, or closes the order once it has waited long enough.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the order fired or expired on this tick.
        """
        expires_at = self.parent.parameters.get('expires_at')
        if isinstance(expires_at, (int, float)) and now >= expires_at:
            if not self.has_fired():
                self.record_state(
                    'cancelled',
                    f'the trigger was not touched within '
                    f'{self.read_valid_days()} days, so it has expired',
                )
                self.save()
                return True
            return False
        return super().on_price_tick(quotes, now)
