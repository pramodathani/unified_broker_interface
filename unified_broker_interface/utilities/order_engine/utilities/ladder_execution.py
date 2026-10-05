"""The execution that spreads an order over several limit orders at evenly spaced prices."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)


class LadderExecution:
    """A plan order's execution that sends `steps` limit orders at once, at prices evenly spaced from `from_price` to `to_price`.

    It keeps the rules of today's ladder. The quantity is divided as evenly as whole units allow, the first rungs taking the remainder, so 100 over three rungs is 34, 33 and 33. Each rung's price is rounded to the tick towards the passive side, so a range that does not divide evenly into ticks gives rungs that rest rather than cross. The rung prices replace whatever the pricing set, so a ladder is sent at its own prices.

    Attributes:
        from_price (decimal.Decimal): The first rung's price.
        to_price (decimal.Decimal): The last rung's price.
        steps (int): How many rungs, from 2 to 20.
    """

    def __init__(self, from_price, to_price, steps):
        """Builds the execution from settings the plan reader has already checked.

        Args:
            from_price (decimal.Decimal): The first rung's price.
            to_price (decimal.Decimal): The last rung's price.
            steps (int): How many rungs.

        Returns:
            None: This method returns nothing.
        """
        self.from_price = from_price
        self.to_price = to_price
        self.steps = steps

    def needs_prices(self):
        """Whether this execution needs the instrument's tick size, which it does, to round its rungs.

        Returns:
            bool: True.
        """
        return True

    def paced_by_ticks(self):
        """Whether this execution sends pieces on later ticks, which it does not; every rung goes at once.

        Returns:
            bool: False.
        """
        return False

    def changes_its_order_to_grow(self):
        """Whether a larger target is met by changing a resting order, which it is not.

        Returns:
            bool: False.
        """
        return False

    def begin(self, plan_order, memory, quotes, now):
        """Readies the execution, which needs nothing.

        Args:
            plan_order (OrderContext): Unused.
            memory (dict): Unused.
            quotes (dict): Unused.
            now (float): Unused.

        Returns:
            None: This method returns nothing.
        """
        del plan_order, memory, quotes, now

    def quantities(self, total, lot=1):
        """Each rung's quantity in whole lots, the first rungs taking the remainder.

        Args:
            total (int): The order's quantity.
            lot (int): The lot every rung must be a whole number of.

        Returns:
            list: One quantity per rung.

        Raises:
            RefusedRequestError: With HTTP 400 when the quantity is fewer lots than the number of rungs.
        """
        lots = total // lot
        if lots < self.steps:
            if lot == 1:
                message = f'a ladder of {self.steps} steps needs a quantity of at least {self.steps}, not {total}'
            else:
                message = f'a ladder of {self.steps} steps needs at least {self.steps} lots of {lot}, not {total}'
            raise RefusedRequestError.refusal(message, 400)
        each = lots // self.steps
        remainder = lots - each * self.steps
        quantities = []
        for index in range(self.steps):
            if index < remainder:
                quantities.append((each + 1) * lot)
            else:
                quantities.append(each * lot)
        return quantities

    def rung_prices(self, plan_order, sending_side):
        """Each rung's price, evenly spaced and rounded to the tick towards the passive side.

        Args:
            plan_order (OrderContext): The order's view of the plan order, which knows the tick size.
            sending_side (str): BUY or SELL.

        Returns:
            list: One price (decimal.Decimal) per rung.
        """
        view = MarketView(None, plan_order.tick_size())
        span = self.to_price - self.from_price
        prices = []
        for index in range(self.steps):
            fraction = decimal.Decimal(index) / decimal.Decimal(self.steps - 1)
            price = view.rounded(self.from_price + span * fraction, sending_side)
            if price is None:
                price = self.from_price + span * fraction
            prices.append(price)
        return prices

    def due_pieces(self, plan_order, memory, total, pieces, quotes, now, sending_side=None):
        """Every rung, the first time it is asked.

        Args:
            plan_order (OrderContext): Unused.
            memory (dict): Unused.
            total (int): The order's quantity.
            pieces (list): The broker orders sent so far.
            quotes (dict): Unused.
            now (float): Unused.
            sending_side (str | None): Unused.

        Returns:
            list: One quantity per rung, or nothing once they are sent.

        Raises:
            RefusedRequestError: With HTTP 400 when the quantity is smaller than the number of rungs.
        """
        del quotes, now, sending_side
        if not self.will_send_more(memory, total, pieces):
            return []
        return self.quantities(total, plan_order.lot_size())

    def will_send_more(self, memory, remaining, pieces):
        """Whether the rungs are still to be sent, which they are only before any has been.

        Args:
            memory (dict): Unused.
            remaining (int): Unused.
            pieces (list): The broker orders sent so far.

        Returns:
            bool: True before the rungs are sent.
        """
        del memory, remaining
        return not pieces

    def described(self):
        """This execution as a dry run shows it.

        Returns:
            dict: The settings.
        """
        return {
            'ladder': {
                'from_price': str(self.from_price),
                'to_price': str(self.to_price),
                'steps': self.steps,
            },
        }
