"""A trigger condition that holds once the price has pulled back from its best by a trailing distance."""

import decimal

HUNDRED = decimal.Decimal('100')


class TrailsCondition:
    """A plan order's trigger condition that follows the best last price and holds once the price pulls back from it by the trail distance.

    It is a trailing stop kept in the engine rather than at the broker. For an order sent as a sell, such as the exit of a long, the best price is the highest seen and the condition holds when the price falls the distance below it; for a buy, the lowest seen and a rise the distance above. Because nothing rests at the broker, the order it triggers can be priced and executed any way the order's other slots say, which a native trailing stop cannot. The price it gives up for that is that it does nothing while the engine is down.

    Attributes:
        points (decimal.Decimal | None): The distance in price, or None when `percent` is used.
        percent (decimal.Decimal | None): The distance as a percentage of the best price, or None when `points` is used.
    """

    def __init__(self, points, percent):
        """Builds the condition from settings the plan reader has already checked.

        Args:
            points (decimal.Decimal | None): The distance in price, or None.
            percent (decimal.Decimal | None): The distance as a percentage, or None.

        Returns:
            None: This method returns nothing.
        """
        self.points = points
        self.percent = percent

    def needs_prices(self):
        """Whether this condition reads quotes, which it always does.

        Returns:
            bool: True.
        """
        return True

    def instruments(self):
        """The instruments other than the order's own that this condition watches, which are none.

        Returns:
            list: An empty list.
        """
        return []

    def prepare(self, plan_order, memory):
        """Readies the condition when the plan is placed, which a trailing condition does not need.

        Args:
            plan_order (PlanOrder): The plan order.
            memory (dict): The condition's memory, unchanged.

        Returns:
            None: This method returns nothing.
        """
        del plan_order, memory

    def improves(self, price, best, sending_side):
        """Whether a price is better than the best seen, for an order sent on this side.

        Args:
            price (decimal.Decimal): The price just seen.
            best (decimal.Decimal | None): The best so far, or None before any.
            sending_side (str): BUY or SELL; a sell follows the highest price and a buy the lowest.

        Returns:
            bool: True when the best price should move to this one.
        """
        if best is None:
            return True
        if sending_side == 'SELL':
            return price > best
        return price < best

    def is_met(self, plan_order, memory, quotes, now, opening_side, sending_side):
        """Whether the price has pulled back from its best by the trail distance, updating the best first.

        Args:
            plan_order (PlanOrder): The plan order, which reads quotes into prices.
            memory (dict): The condition's memory, whose `best` is updated in place.
            quotes (dict): The quotes the tick carried.
            now (float): Unused.
            opening_side (str): Unused.
            sending_side (str): BUY or SELL, the side the order will be sent on.

        Returns:
            bool: True when the pullback has been reached.
        """
        del now, opening_side
        price = plan_order.view(quotes).last()
        if price is None:
            return False
        best = None
        if memory.get('best') is not None:
            best = decimal.Decimal(str(memory['best']))
        if self.improves(price, best, sending_side):
            best = price
            memory['best'] = str(best)
        if self.points is not None:
            distance = self.points
        else:
            distance = best * self.percent / HUNDRED
        if sending_side == 'SELL':
            return price <= best - distance
        return price >= best + distance

    def described(self):
        """This condition as a dry run shows it.

        Returns:
            dict: The distance.
        """
        if self.points is not None:
            settings = {
                'points': str(self.points),
            }
        else:
            settings = {
                'percent': str(self.percent),
            }
        return {
            'trails': settings,
        }
