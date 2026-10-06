"""The venue that never sends an order, and fills it on paper from the virtual book's queue estimate and the book it would have met."""

import decimal

from unified_broker_interface.utilities.execution_costs.book_walk import (
    BookWalk,
)

OPPOSITE_DEPTH_SIDES = {
    'BUY': 'sell',
    'SELL': 'buy',
}
AVERAGE_PRICE_PLACES = decimal.Decimal('0.0001')


class PaperVenue:
    """A plan order's venue that keeps the order on paper instead of sending it to a broker.

    It keeps the rules of today's virtual limit type with `paper: true`. The order waits on a `limit_marketable` trigger, which the plan reader insists on, so `bin/unified/orders/virtual_book` follows its place in the queue. Two things fill it, and each fill is recorded as a `paper_filled` event with the average price of everything filled so far:

    1. **The queue.** As the queue ahead of a resting order trades away, or a trade happens beyond its price, the estimate's `queue_filled` grows, and that quantity fills at the order's limit price, as a resting order's would.
    2. **The other side reaching the price.** That is the moment a real order would be sent, and a real order would then take only what the book offers at its price or better, at those prices. So, once, at that moment, the order walks the levels of the other side at or better than its limit, and fills what they hold. Whatever is left keeps resting and fills from the queue.

    The order is done once its whole quantity has filled. A touch seen without a quote to walk, as on a tick that carried no quote for the instrument, waits for the next tick that does.
    """

    def check(self, context, now=None):
        """Checks the order can be kept on paper, which needs nothing beyond what the plan reader checked.

        Args:
            context (OrderContext): Unused.
            now (datetime.datetime | None): Unused.

        Returns:
            None: This method returns nothing.
        """
        del context, now

    def fill(self, plan_order, part, quotes=None):
        """Records whatever more the queue and the book say the order would have filled, and ends the order once it has filled completely.

        Args:
            plan_order (PlanOrder): The plan order.
            part (OrderPart): The order, whose trigger is a `limit_marketable` condition.
            quotes (dict | None): The quotes the tick carried, or None when it carried none.

        Returns:
            bool: True when a fill was recorded.
        """
        estimate = part.trigger.estimate(plan_order, part.path)
        if estimate is None:
            return False
        queue_filled = self.whole_number(estimate.get('queue_filled'))
        estimated_filled = self.whole_number(estimate.get('filled'))
        if queue_filled is None or estimated_filled is None:
            return False
        record = plan_order.part_record(part.path)
        held = ((record.get('memory') or {}).get('trigger') or {}).get('held') or {}
        quantity = int(held.get('quantity') or 0)
        limit_price = self.price(held.get('price'))
        transaction_type = held.get('transaction_type')
        touched = estimated_filled > queue_filled
        walked_now = False
        if touched and record.get('paper_touch') is None and quotes is not None:
            touch = self.walk_the_touch(plan_order, quotes, transaction_type, limit_price, quantity - queue_filled)
            if touch is not None:
                record['paper_touch'] = touch
                walked_now = True
        touch = record.get('paper_touch') or {}
        touch_quantity = int(touch.get('quantity') or 0)
        filled = min(quantity, queue_filled + touch_quantity)
        already = record.get('paper_filled') or 0
        if filled <= already:
            if walked_now:
                plan_order.set_part_record(part.path, record, f'the plan\'s {part.path} part became marketable on paper, but the book offered nothing more at its price')
            return False
        average_price = self.average_price(filled, touch_quantity, touch.get('average_price'), limit_price)
        plan_order.record({
            'event': 'paper_filled',
            'parent_state': plan_order.parent.state,
            'path': part.path,
            'transaction_type': transaction_type,
            'quantity': quantity,
            'filled_quantity': filled,
            'price': plan_order.json_number(held.get('price')),
            'average_price': plan_order.json_number(average_price),
            'detail': {
                'estimate': estimate,
                'touch': record.get('paper_touch'),
            },
        })
        if plan_order.parent.state == 'received':
            plan_order.record_state('working', f'paper fill of {filled} of {quantity}')
        record['paper_filled'] = filled
        message = f'the plan\'s {part.path} part filled {filled} of {quantity} on paper'
        if filled >= quantity:
            record['state'] = 'done'
            record['reason'] = 'filled_on_paper'
            message = f'the plan\'s {part.path} part filled on paper: {filled} at an average of {average_price}'
        plan_order.set_part_record(part.path, record, message)
        return True

    def walk_the_touch(self, plan_order, quotes, transaction_type, limit_price, wanted):
        """What a real order sent as the other side reached its price would have taken: the levels at or better than the limit, best first.

        Args:
            plan_order (PlanOrder): The plan order, whose view reads the quote.
            quotes (dict): The quotes the tick carried.
            transaction_type (str): `BUY` or `SELL`.
            limit_price (decimal.Decimal | None): The order's limit price.
            wanted (int): The quantity still to fill.

        Returns:
            dict | None: `quantity` taken (int) and `average_price` (float | None), or None when there is no readable, fresh quote to walk.
        """
        view = plan_order.view(quotes)
        if not view.is_readable() or view.is_stale() or limit_price is None:
            return None
        side = OPPOSITE_DEPTH_SIDES.get(transaction_type)
        if side is None:
            return None
        reachable = []
        for price, level_quantity in view.levels_with_quantity(side):
            if transaction_type == 'BUY' and price > limit_price:
                break
            if transaction_type == 'SELL' and price < limit_price:
                break
            reachable.append((price, level_quantity))
        walk = BookWalk(max(wanted, 0), reachable)
        average = walk.average_price()
        if average is None:
            return {
                'quantity': 0,
                'average_price': None,
            }
        return {
            'quantity': walk.filled_quantity(),
            'average_price': float(average.quantize(AVERAGE_PRICE_PLACES)),
        }

    def average_price(self, filled, touch_quantity, touch_price, limit_price):
        """The average price of everything filled so far: the touch's quantity at its walked price, and the rest at the limit.

        Args:
            filled (int): The quantity filled so far.
            touch_quantity (int): How much of it the touch filled.
            touch_price (float | None): The touch's average price.
            limit_price (decimal.Decimal | None): The order's limit price.

        Returns:
            decimal.Decimal | None: The average, rounded to four places, or None when a price is missing.
        """
        if filled <= 0:
            return None
        from_touch = min(touch_quantity, filled)
        from_queue = filled - from_touch
        total = decimal.Decimal(0)
        if from_touch > 0:
            if touch_price is None:
                return None
            total = total + decimal.Decimal(str(touch_price)) * from_touch
        if from_queue > 0:
            if limit_price is None:
                return None
            total = total + limit_price * from_queue
        return (total / filled).quantize(AVERAGE_PRICE_PLACES)

    def whole_number(self, value):
        """A count from the stored estimate.

        Args:
            value (object): The value.

        Returns:
            int | None: The count, or None when it is not a whole number.
        """
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    def price(self, value):
        """A price from the order's held memory.

        Args:
            value (object): The value, a JSON number.

        Returns:
            decimal.Decimal | None: The price, or None when it is missing or unusable.
        """
        if value is None or isinstance(value, bool):
            return None
        try:
            price = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            return None
        if not price.is_finite() or price <= 0:
            return None
        return price

    def described(self):
        """This venue as a dry run shows it.

        Returns:
            dict: The session.
        """
        return {
            'session': 'paper',
        }
