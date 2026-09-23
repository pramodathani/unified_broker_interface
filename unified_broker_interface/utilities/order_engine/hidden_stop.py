"""A stop nobody can see, watching the book instead of the last trade."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.price_trigger import (
    PriceTrigger,
)

DEFAULT_BUFFER_TICKS = 2


class HiddenStop(PriceTrigger):
    """A stop that lives in the engine, with an optional far-away native stop behind it.

    `transaction_type` is the side that **opened** the position, as it is for every type that protects one, so a long is protected by asking for a BUY and the exit this sends is a sell.

    Two things are bought by keeping the stop here rather than at the exchange, and one large thing is given up.

    What is bought is the trigger. A native stop watches the last traded price, so a single stray trade at a silly price — the freak trades that got stop-loss-market withdrawn in the first place — takes you out of a position the market never really left. This watches the **bid** when protecting a long and the **offer** when protecting a short, which are prices somebody is actually standing behind. It also fires in whichever direction the caller asks, where a native stop only fires away from the position.

    What is given up is everything. Nothing is at the exchange, so nothing protects the position while the engine, the machine, the network or the quote feed is down, and the Atlas is blunt that this is the one thing a native stop has that no amount of code replaces.

    That is what `backstop_price` and `backstop_limit_price` are for. They place a real stop-loss limit, deliberately further away than the hidden one, when the parent is armed. In normal running the hidden stop fires first, cancels the backstop and exits on its own terms. If the engine is not there, the backstop is, further away and worse but real.
    """

    SYNTHETIC_TYPE = 'hidden_stop'
    ARMED_MESSAGE = 'the book reaches the level'

    def default_direction(self, transaction_type):
        """Which way the price has to move for a stop on this position to fire.

        A long is stopped out by the price falling and a short by it rising, which is the opposite of the buy-the-dip default every other trigger takes.

        Args:
            transaction_type (str): The side that opened the position.

        Returns:
            str: One of `DIRECTIONS`.
        """
        return 'at_or_below' if transaction_type == 'BUY' else 'at_or_above'

    def watched_price(self, view):
        """The price on the side that would have to take the exit, rather than the last trade.

        A long is exited by selling into the bid, so the bid is what decides whether the stop should fire: it is the price somebody is actually standing behind and willing to pay. Using the last traded price instead is what lets one stray print at a price nobody was standing behind close a position.

        The bid is the exit's *opposite* touch, not its own. A sell rests on the offer and fills against the bid, and it is the fill that matters here, so reading the exit's own side would watch the wrong half of the book by exactly one spread.

        Args:
            view (MarketView): The instrument's quote.

        Returns:
            decimal.Decimal | None: The price, or None when that side of the book is empty.
        """
        order = self.read_order(self.parent.body)
        side = self.exit_side(order.transaction_type)
        price = view.opposite_touch(side)
        if price is not None:
            return price
        return view.last()

    def read_buffer_ticks(self):
        """How far past the touch the exit it fires is priced.

        Returns:
            int: The buffer in ticks.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a whole number of ticks at or above zero.
        """
        value = self.parent.parameters.get(
            'buffer_ticks',
            DEFAULT_BUFFER_TICKS,
        )
        try:
            ticks = int(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'buffer_ticks must be a whole number of ticks, not {value!r}',
                400,
            )
        if ticks < 0:
            raise RefusedRequestError.refusal(
                f'buffer_ticks cannot be negative, not {ticks}',
                400,
            )
        return ticks

    def backstop_prices(self):
        """The trigger and limit of the native stop left behind the hidden one.

        Returns:
            tuple: The trigger price and limit price as `decimal.Decimal`, or `(None, None)` when the caller asked for no backstop.

        Raises:
            RefusedRequestError: With HTTP 400 when only one of the two is given, or either is not a price above zero.
        """
        trigger = self.parent.parameters.get('backstop_price')
        limit = self.parent.parameters.get('backstop_limit_price')
        if trigger is None and limit is None:
            return None, None
        if trigger is None or limit is None:
            raise RefusedRequestError.refusal(
                'a backstop needs both backstop_price and '
                'backstop_limit_price: a stop-limit whose limit sits at its '
                'trigger will not fill when the price runs through it, which '
                'is what a backstop is for',
                400,
            )
        prices = []
        for name, value in (
            ('backstop_price', trigger),
            ('backstop_limit_price', limit),
        ):
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

    def arm(self, order, started_at):
        """Places the native stop that protects the position while the engine is not there.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            None: This method returns nothing.
        """
        trigger, limit = self.backstop_prices()
        if trigger is None:
            return
        body = dict(self.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body['order_type'] = 'SL'
        body['quantity'] = order.quantity
        body['transaction_type'] = self.exit_side(order.transaction_type)
        body['price'] = str(limit)
        body['trigger_price'] = str(trigger)
        answer, _, _ = self.place_leg(
            'backstop',
            self.read_order(body),
            started_at,
        )
        if answer.get('outcome') == 'accepted':
            self.record_state('protecting', 'the backstop is resting')
        self.save()

    def child_order(self, order, view):
        """A limit priced past the touch, which closes the position against what is resting.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            view (MarketView): The traded instrument's quote at the moment it fired.

        Returns:
            PlaceOrderRequest | None: The order to place, or None when the book has no side to price against.
        """
        side = self.exit_side(order.transaction_type)
        touch = view.opposite_touch(side)
        if touch is None:
            return None
        price = view.moved(touch, self.read_buffer_ticks(), side, True)
        price = view.rounded(price, side)
        if price is None or price <= 0:
            return None
        return self.priced(order, price, side)

    def fire(self, child, price, level):
        """Cancels the backstop and then exits, in that order.

        The backstop goes first for the reason every kill switch goes first: a resting stop that is left alone while the exit fills can trigger afterwards and open a brand new position in the opposite direction, unattended, with nothing watching it.

        Args:
            child (PlaceOrderRequest): The exit to place.
            price (decimal.Decimal): The watched price that fired it.
            level (decimal.Decimal): The level it reached.

        Returns:
            bool: True, because the stop fired whatever the broker then said.
        """
        for leg in self.parent.legs:
            if leg.role != 'backstop' or leg.is_finished():
                continue
            if leg.broker_order_id is None:
                continue
            self.cancel_leg(
                leg,
                'the hidden stop fired, so the backstop is no longer needed',
            )
        self.save()
        return super().fire(child, price, level)
