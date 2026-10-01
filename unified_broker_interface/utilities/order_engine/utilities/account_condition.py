"""The trigger condition that holds when a figure from the account reaches a level."""

import decimal
import json

import redis

FUNDS_KEY = 'unified:portfolio:funds'
ACCOUNT_FIELDS = (
    'available_balance',
    'day_pnl',
    'open_positions',
)
DIRECTIONS = (
    'at_or_above',
    'at_or_below',
)


class AccountCondition:
    """A plan order's trigger condition on the account rather than on a price.

    It keeps the rules of today's account-conditional type. The figure is `available_balance`, the free margin across every broker from `unified:portfolio:funds`; `day_pnl`, realized plus unrealized profit across every broker from the same document; or `open_positions`, how many net positions are open. It holds when the figure is at or above, or at or below, `level`; the direction is required, since nothing about an order says which way an account figure should move. It reads no quotes, so the clock ticks check it once a second.

    Attributes:
        field (str): One of `ACCOUNT_FIELDS`.
        level (decimal.Decimal): The level.
        direction (str): One of `DIRECTIONS`.
    """

    def __init__(self, field, level, direction):
        """Builds the condition from settings the plan reader has already checked.

        Args:
            field (str): The figure.
            level (decimal.Decimal): The level.
            direction (str): The direction.

        Returns:
            None: This method returns nothing.
        """
        self.field = field
        self.level = level
        self.direction = direction

    def needs_prices(self):
        """Whether this condition reads quotes, which it does not.

        Returns:
            bool: False.
        """
        return False

    def instruments(self):
        """The instruments this condition watches, which are none.

        Returns:
            list: An empty list.
        """
        return []

    def prepare(self, plan_order, memory):
        """Readies the condition, which needs nothing.

        Args:
            plan_order (OrderContext): Unused.
            memory (dict): Unused.

        Returns:
            None: This method returns nothing.
        """
        del plan_order, memory

    def funds_figure(self, plan_order):
        """The free margin or the day's profit and loss across every broker.

        Args:
            plan_order (OrderContext): The order's view of the plan order, whose placement reads Redis.

        Returns:
            decimal.Decimal | None: The figure, or None when it cannot be read.
        """
        try:
            stored = plan_order.placement.cache.get(FUNDS_KEY)
        except redis.RedisError:
            return None
        if not stored:
            return None
        try:
            document = json.loads(stored)
        except ValueError:
            return None
        if not isinstance(document, dict):
            return None
        if self.field == 'available_balance':
            value = (document.get('summary') or {}).get('available_balance')
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            return decimal.Decimal(str(value))
        profit_and_loss = document.get('pnl')
        if not isinstance(profit_and_loss, dict):
            return None
        total = decimal.Decimal(0)
        for name in ('realized', 'unrealized'):
            value = profit_and_loss.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                total = total + decimal.Decimal(str(value))
        return total

    def open_position_count(self, plan_order):
        """How many net positions are open across every broker.

        Args:
            plan_order (OrderContext): The order's view of the plan order, whose placement reads the positions.

        Returns:
            decimal.Decimal | None: The count, or None when the positions cannot be read.
        """
        _, _, positions = plan_order.placement.market_context(plan_order.instrument_id, False, True)
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

    def figure(self, plan_order):
        """The account figure the condition compares.

        Args:
            plan_order (OrderContext): The order's view of the plan order.

        Returns:
            decimal.Decimal | None: The figure, or None when it cannot be read.
        """
        if self.field == 'open_positions':
            return self.open_position_count(plan_order)
        return self.funds_figure(plan_order)

    def is_met(self, plan_order, memory, quotes, now, opening_side, sending_side):
        """Whether the account figure has reached the level.

        Args:
            plan_order (OrderContext): The order's view of the plan order.
            memory (dict): Unused.
            quotes (dict): Unused.
            now (float): Unused.
            opening_side (str): Unused.
            sending_side (str): Unused.

        Returns:
            bool: True when it holds.
        """
        del memory, quotes, now, opening_side, sending_side
        figure = self.figure(plan_order)
        if figure is None:
            return False
        if self.direction == 'at_or_above':
            return figure >= self.level
        return figure <= self.level

    def described(self):
        """This condition as a dry run shows it.

        Returns:
            dict: The settings.
        """
        return {
            'account': {
                'field': self.field,
                'level': str(self.level),
                'direction': self.direction,
            },
        }
