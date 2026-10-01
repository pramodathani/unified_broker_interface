"""The pricing modifier that quietly takes a better price than the one an order shows."""

import decimal

BUFFER_TICKS = 2


class DiscretionModifier:
    """A plan order's discretion: the visible limit rests where it was priced, and when the other side comes within `points` of it, the engine takes that price without ever having shown it.

    It keeps the rules of today's discretionary type. A buy resting at 1000 with 0.25 of discretion takes an offer of 1000.20 when one appears. The taking order is a limit `BUFFER_TICKS` past the other side's touch, never past the visible price plus the discretion. `quantity` is how much is taken, and defaults to all that is still resting. The visible order is reduced, or cancelled when all of it is taken, before the taking order is sent, so the two can never both fill in full.

    Only the part's first broker order is the visible one, so a taking order that rests is never itself treated as visible and taken from again.

    Attributes:
        points (decimal.Decimal): How far past its visible price the order will go.
        quantity (int | None): How much is taken at once, or None for all that rests.
    """

    def __init__(self, points, quantity):
        """Builds the modifier from settings the plan reader has already checked.

        Args:
            points (decimal.Decimal): How far past its visible price the order will go.
            quantity (int | None): How much is taken at once, or None for all that rests.

        Returns:
            None: This method returns nothing.
        """
        self.points = points
        self.quantity = quantity

    def reachable_price(self, leg):
        """The worst price the visible order will quietly take.

        Args:
            leg (OrderLeg): The visible order.

        Returns:
            decimal.Decimal: The price.
        """
        visible = decimal.Decimal(str(leg.price))
        if leg.transaction_type == 'BUY':
            return visible + self.points
        return visible - self.points

    def within_reach(self, touch, leg):
        """Whether the other side's touch is within the discretion.

        Args:
            touch (decimal.Decimal): The other side's best price.
            leg (OrderLeg): The visible order.

        Returns:
            bool: True when it should be taken.
        """
        reachable = self.reachable_price(leg)
        if leg.transaction_type == 'BUY':
            return touch <= reachable
        return touch >= reachable

    def taking_quantity(self, resting):
        """How much to take now.

        Args:
            resting (int): How much of the visible order is still resting.

        Returns:
            int: The quantity.
        """
        if self.quantity is None:
            return resting
        return min(self.quantity, resting)

    def taking_price(self, view, touch, leg):
        """The taking order's limit: a little past the touch, never past what the discretion allows.

        Args:
            view (MarketView): The order's quote.
            touch (decimal.Decimal): The other side's best price.
            leg (OrderLeg): The visible order.

        Returns:
            decimal.Decimal | None: The limit, or None when it cannot be rounded.
        """
        price = view.moved(touch, BUFFER_TICKS, leg.transaction_type, True)
        price = view.rounded(price, leg.transaction_type)
        if price is None or price <= 0:
            return None
        reachable = self.reachable_price(leg)
        if leg.transaction_type == 'BUY':
            return min(price, reachable)
        return max(price, reachable)

    def take(self, plan_order, part, quotes):
        """Takes the other side's price when it has come within reach of the visible order.

        Args:
            plan_order (PlanOrder): The plan order.
            part (OrderPart): The order the discretion belongs to.
            quotes (dict): The quotes the tick carried.

        Returns:
            bool: True when a taking order was sent.
        """
        legs = part.own_legs(plan_order.parent)
        if not legs:
            return False
        visible = legs[0]
        if visible.is_finished() or visible.price is None or not visible.broker_order_id:
            return False
        view = plan_order.view(quotes)
        touch = view.opposite_touch(visible.transaction_type)
        if touch is None or not self.within_reach(touch, visible):
            return False
        resting = (visible.quantity or 0) - (visible.filled_quantity or 0)
        if resting < 1:
            return False
        taking = self.taking_quantity(resting)
        price = self.taking_price(view, touch, visible)
        if price is None:
            return False
        reason = f'the other side reached {touch}, which is inside the discretion, so {taking} is being taken'
        if taking >= resting:
            made_room = plan_order.cancel_leg(visible, reason)
        else:
            made_room = plan_order.reduce_leg(visible, (visible.quantity or 0) - taking, reason)
        if not made_room:
            return False
        body = dict(plan_order.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        if not part.keeps_tag:
            body.pop('tag', None)
        body['order_type'] = 'LIMIT'
        body['quantity'] = taking
        body['transaction_type'] = visible.transaction_type
        body['price'] = str(price)
        plan_order.place_leg(part.path, plan_order.read_order(body), None, plan_order.chosen_broker())
        return True

    def described(self):
        """This modifier as a dry run shows it.

        Returns:
            dict: The settings.
        """
        return {
            'discretion': {
                'points': str(self.points),
                'quantity': self.quantity,
            },
        }
