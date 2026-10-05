"""A trigger condition that holds once a price has reached a level."""

import decimal

DIRECTIONS = (
    'at_or_above',
    'at_or_below',
)
FIELDS = (
    'last',
    'bid',
    'ask',
    'mid',
    'average_price',
    'previous_close',
    'opposite_touch',
)
CONFIRMATIONS = (
    'none',
    'double_last',
    'held',
)


class PriceCrossesCondition:
    """A plan order's trigger condition that holds once a chosen price has reached a level from the side that fires.

    It keeps the rules of today's price-triggered types. With no direction given, an order opened with a buy waits for the price to fall to the level and one opened with a sell waits for it to rise, which is a market-if-touched order's meaning for an entry and a stop's meaning for an exit that protects the position. `double_last` needs two ticks in a row at or through the level and `held` needs the level to stay reached for `hold_seconds`; a tick that does not reach it starts the count again.

    Attributes:
        level (decimal.Decimal): The level.
        direction (str | None): One of `DIRECTIONS`, or None for the default from the side that opened the order.
        field (str): Which price out of the quote is compared, one of `FIELDS`.
        instrument_id (str | None): The instrument watched, or None for the order's own.
        confirm (str): One of `CONFIRMATIONS`.
        hold_seconds (decimal.Decimal | None): How long a `held` confirmation needs, or None.
    """

    def __init__(self, level, direction, field, instrument_id, confirm, hold_seconds):
        """Builds the condition from settings the plan reader has already checked.

        Args:
            level (decimal.Decimal): The level.
            direction (str | None): One of `DIRECTIONS`, or None for the default.
            field (str): One of `FIELDS`.
            instrument_id (str | None): The instrument watched, or None for the order's own.
            confirm (str): One of `CONFIRMATIONS`.
            hold_seconds (decimal.Decimal | None): The hold time for `held`, or None.

        Returns:
            None: This method returns nothing.
        """
        self.level = level
        self.direction = direction
        self.field = field
        self.instrument_id = instrument_id
        self.confirm = confirm
        self.hold_seconds = hold_seconds

    def needs_prices(self):
        """Whether this condition reads quotes, which it always does.

        Returns:
            bool: True.
        """
        return True

    def instruments(self):
        """The instruments other than the order's own that this condition watches.

        Returns:
            list: The instrument ids, empty when it watches the order's own.
        """
        if self.instrument_id is None:
            return []
        return [
            self.instrument_id,
        ]

    def prepare(self, plan_order, memory):
        """Readies the condition when the plan is placed, which a price condition does not need.

        Args:
            plan_order (PlanOrder): The plan order.
            memory (dict): The condition's memory, unchanged.

        Returns:
            None: This method returns nothing.
        """
        del plan_order, memory

    def effective_direction(self, opening_side):
        """Which way the price has to move for this condition to hold.

        Args:
            opening_side (str): BUY or SELL, the side the caller's order was opened with.

        Returns:
            str: One of `DIRECTIONS`.
        """
        if self.direction is not None:
            return self.direction
        if opening_side == 'BUY':
            return 'at_or_below'
        return 'at_or_above'

    def watched_price(self, view, sending_side):
        """The price out of the watched quote that is compared with the level.

        Args:
            view (MarketView): The watched instrument's quote.
            sending_side (str): BUY or SELL, the side the order will be sent on, which `opposite_touch` is read against.

        Returns:
            decimal.Decimal | None: The price, or None when the quote does not carry it.
        """
        if self.field == 'bid':
            return view.best_bid()
        if self.field == 'ask':
            return view.best_offer()
        if self.field == 'mid':
            return view.mid()
        if self.field == 'opposite_touch':
            return view.opposite_touch(sending_side)
        if self.field in ('average_price', 'previous_close'):
            if not view.is_readable():
                return None
            return view.number(view.quote.get(self.field))
        return view.last()

    def is_met(self, plan_order, memory, quotes, now, opening_side, sending_side):
        """Whether the level has been reached, and confirmed the way `confirm` asks, on this tick.

        A quote marked stale is treated as no quote at all: it neither fires the condition nor counts towards a confirmation, and it does not start the count again. The quote combiner marks a quote stale when the broker it came from has gone silent with no healthy backup, so its price may be minutes old.

        Args:
            plan_order (PlanOrder): The plan order, which reads quotes into prices.
            memory (dict): The condition's memory between ticks, changed in place.
            quotes (dict): The quotes the tick carried, by instrument id.
            now (float): The Unix time of the tick.
            opening_side (str): BUY or SELL, the side the caller's order was opened with.
            sending_side (str): BUY or SELL, the side the order will be sent on.

        Returns:
            bool: True when the condition holds on this tick.
        """
        view = plan_order.view(quotes, self.instrument_id)
        if view.is_stale():
            return False
        price = self.watched_price(view, sending_side)
        if price is None:
            return False
        if self.effective_direction(opening_side) == 'at_or_above':
            reached = price >= self.level
        else:
            reached = price <= self.level
        if self.confirm == 'none':
            return reached
        if not reached:
            memory.pop('reached_ticks', None)
            memory.pop('reached_since', None)
            return False
        if self.confirm == 'double_last':
            count = int(memory.get('reached_ticks') or 0) + 1
            memory['reached_ticks'] = count
            return count >= 2
        since = memory.get('reached_since')
        if since is None:
            memory['reached_since'] = now
            since = now
        held_for = decimal.Decimal(str(now)) - decimal.Decimal(str(since))
        return held_for >= self.hold_seconds

    def described(self):
        """This condition as a dry run shows it.

        Returns:
            dict: The condition's settings.
        """
        settings = {
            'level': str(self.level),
            'direction': self.direction or 'from the opening side',
            'field': self.field,
            'confirm': self.confirm,
        }
        if self.instrument_id is not None:
            settings['instrument_id'] = self.instrument_id
        if self.hold_seconds is not None:
            settings['hold_seconds'] = str(self.hold_seconds)
        return {
            'price_crosses': settings,
        }
