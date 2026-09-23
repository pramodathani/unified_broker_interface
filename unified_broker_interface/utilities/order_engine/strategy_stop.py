"""A stop on a whole strategy's profit and loss rather than on any one leg's price."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.basket import Basket

DEFAULT_BUFFER_TICKS = 2


class StrategyStop(Basket):
    """A basket that adds up what all its legs are worth and closes the lot when the total crosses a line.

    An iron condor has four legs and no single one of them says whether the trade is working. Put a stop on the short call and it is taken out by a move that the long call above it has already paid for. The only number that means anything is the total, and no exchange will ever watch a total, because it has no idea which four orders somebody considers one trade.

    So this places the strategy as a basket, remembers what each leg filled at, and on every price tick marks each leg to the market and adds them up. When the total is below `loss_limit` or above `profit_target`, every leg is closed.

    **The exit order matters and is not alphabetical.** Shorts are closed first, then the hedges that were protecting them. Closing a long hedge while its short is still open turns a defined-risk position into a naked one for as long as the second order takes, and a broker looking at the account in that instant sees a margin requirement several times larger — which is exactly the moment it can refuse the second order and leave the position stuck that way.

    `loss_limit` is negative and `profit_target` is positive, both in rupees against the whole strategy, and either may be left out. The mark is the traded instrument's last price, so this measures roughly what a broker's own position screen shows rather than what the position could actually be closed at. On a wide book those differ, and the difference is against you.
    """

    SYNTHETIC_TYPE = 'strategy_stop'
    WANTS_PRICES = True

    def read_limits(self):
        """The loss and profit levels the whole strategy is watched against.

        Returns:
            tuple: The loss limit and profit target as `decimal.Decimal` or None.

        Raises:
            RefusedRequestError: With HTTP 400 when neither is given, or either is not a number with the right sign.
        """
        loss = self.number('loss_limit')
        profit = self.number('profit_target')
        if loss is None and profit is None:
            raise RefusedRequestError.refusal(
                'a strategy stop needs loss_limit, profit_target, or both',
                400,
            )
        if loss is not None and loss >= 0:
            raise RefusedRequestError.refusal(
                f'loss_limit is a loss, so it must be below zero, not {loss}',
                400,
            )
        if profit is not None and profit <= 0:
            raise RefusedRequestError.refusal(
                f'profit_target must be above zero, not {profit}',
                400,
            )
        return loss, profit

    def number(self, name):
        """One of the caller's levels, as a number.

        Args:
            name (str): The parameter's name.

        Returns:
            decimal.Decimal | None: The value, or None when it was not given.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a number.
        """
        value = self.parent.parameters.get(name)
        if value is None:
            return None
        try:
            number = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'{name} must be a number, not {value!r}',
                400,
            )
        if not number.is_finite():
            raise RefusedRequestError.refusal(
                f'{name} must be a number, not {value!r}',
                400,
            )
        return number

    def run(self, intent, started_at):
        """Places the strategy, having checked it has something to watch for.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when the levels or the candidates cannot be read.
        """
        self.read_limits()
        self.remember_tick_size(self.read_order(self.parent.body))
        return super().run(intent, started_at)

    def leg_profit(self, leg, quotes):
        """What one leg is worth now against what it was filled at.

        Args:
            leg (OrderLeg): The leg.
            quotes (dict): The quotes the tick carried.

        Returns:
            decimal.Decimal | None: The profit in rupees, or None when the leg cannot be marked.
        """
        if leg.role != 'basket' or not leg.filled_quantity:
            return None
        entered_at = leg.average_price or leg.price
        if not entered_at:
            return None
        view = self.view(quotes, leg.instrument_id)
        now = view.last()
        if now is None:
            return None
        moved = now - decimal.Decimal(str(entered_at))
        if leg.transaction_type == 'SELL':
            moved = -moved
        return moved * leg.filled_quantity

    def total_profit(self, quotes):
        """What the whole strategy is worth now.

        Args:
            quotes (dict): The quotes the tick carried.

        Returns:
            tuple: The total as `decimal.Decimal`, and whether every filled leg could be marked (bool).
        """
        total = decimal.Decimal('0')
        complete = True
        for leg in self.parent.legs:
            if leg.role != 'basket' or not leg.filled_quantity:
                continue
            profit = self.leg_profit(leg, quotes)
            if profit is None:
                complete = False
                continue
            total = total + profit
        return total, complete

    def on_price_tick(self, quotes, now):
        """Closes the whole strategy once its total crosses a level.

        The total is only acted on when every filled leg could be marked. A condor with one leg's quote missing is not a three-legged condor worth acting on: it is a number that happens to be smaller than the truth, and closing on it would be closing on a measurement error.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the strategy was closed on this tick.
        """
        if self.parent.parameters.get('closed_at') is not None:
            return False
        loss, profit = self.read_limits()
        total, complete = self.total_profit(quotes)
        if not complete:
            return False
        reason = None
        if loss is not None and total <= loss:
            reason = f'the strategy is down {total}, past its limit of {loss}'
        elif profit is not None and total >= profit:
            reason = f'the strategy is up {total}, past its target of {profit}'
        if reason is None:
            return False
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['closed_at'] = now
        self.parent.parameters['closed_at_profit'] = str(total)
        self.save()
        self.close_everything(quotes, reason)
        return True

    def exit_order(self, leg, quotes):
        """The order that closes one leg, priced to trade now.

        Args:
            leg (OrderLeg): The leg to close.
            quotes (dict): The quotes the tick carried.

        Returns:
            PlaceOrderRequest | None: The order, or None when the book gives nothing to price against.
        """
        side = 'SELL' if leg.transaction_type == 'BUY' else 'BUY'
        view = self.view(quotes, leg.instrument_id)
        touch = view.opposite_touch(side)
        if touch is None:
            touch = view.last()
        if touch is None:
            return None
        price = view.moved(touch, DEFAULT_BUFFER_TICKS, side, True)
        price = view.rounded(price, side)
        if price is None or price <= 0:
            return None
        body = dict(self.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body.pop('synthetic', None)
        body['order_type'] = 'LIMIT'
        body['quantity'] = leg.filled_quantity
        body['transaction_type'] = side
        body['product'] = leg.product
        body['price'] = str(price)
        return self.read_order(body)

    def close_everything(self, quotes, reason):
        """Closes every filled leg, the shorts before the hedges that cover them.

        Args:
            quotes (dict): The quotes the tick carried.
            reason (str): Why, for a person reading the parent later.

        Returns:
            None: This method returns nothing.
        """
        shorts = []
        longs = []
        for leg in self.parent.legs:
            if leg.role != 'basket' or not leg.filled_quantity:
                continue
            if leg.transaction_type == 'SELL':
                shorts.append(leg)
            else:
                longs.append(leg)
        for leg in shorts + longs:
            order = self.exit_order(leg, quotes)
            if order is None:
                continue
            self.place_leg(
                'close',
                order,
                None,
                leg.broker,
                leg.instrument_id,
            )
        self.record_state('completed', reason)
        self.save()
