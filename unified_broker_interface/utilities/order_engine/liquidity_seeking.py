"""An order that shows nothing and strikes only when the other side is big enough."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder


class LiquiditySeeking(SyntheticOrder):
    """An order that waits, invisible, until enough size appears at a price it likes, then takes it.

    Also called a sniper. It is the opposite discipline from every resting type in this package. A peg, a chaser and an iceberg all put something in the book and wait to be traded against. This puts nothing in the book at all, watches the other side, and sends an order only in the moment when the displayed size at an acceptable price is at least `minimum_quantity`.

    What it is for is an illiquid instrument where showing your hand is the whole cost. A large bid resting in a thin option book tells everybody that somebody wants size, and the offers move away. A sniper leaves no trace between strikes, so the book never adjusts to it.

    It takes the levels it can reach and adds up what is there. `limit_price` is the worst price it will pay, so only levels at or inside it count, which is what stops it being tempted by a large quantity offered somewhere useless. If the total across those levels reaches the threshold, it sends a limit at `limit_price` for the smaller of what is available and what is left to do.

    **The size it sees is the size that is displayed**, and the two are not the same thing. Part of the book may be an iceberg showing a fraction of itself, in which case more fills than expected, which is harmless. Or the size may be gone by the time the order arrives, in which case less fills, the rest of the order rests at the limit, and the next tick finds it already resting rather than starting again. Both are the ordinary gap between seeing and acting, and neither can be closed from here.
    """

    SYNTHETIC_TYPE = 'liquidity_seeking'
    WANTS_PRICES = True

    def read_limit_price(self):
        """The worst price this order will pay.

        Returns:
            decimal.Decimal: The limit price.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or is not a price above zero.
        """
        value = self.parent.parameters.get('limit_price')
        if value is None:
            raise RefusedRequestError.refusal(
                'a liquidity-seeking order needs limit_price, the worst price '
                'it will accept when it strikes',
                400,
            )
        try:
            price = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'limit_price must be a price, not {value!r}',
                400,
            )
        if price <= 0:
            raise RefusedRequestError.refusal(
                f'limit_price must be above zero, not {price}',
                400,
            )
        return price

    def read_minimum_quantity(self):
        """How much has to be showing before this order is worth sending.

        Returns:
            int: The threshold in units.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a whole number above zero.
        """
        value = self.parent.parameters.get('minimum_quantity')
        if value is None:
            raise RefusedRequestError.refusal(
                'a liquidity-seeking order needs minimum_quantity, the size '
                'that has to be showing before it strikes',
                400,
            )
        try:
            quantity = int(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'minimum_quantity must be a whole number, not {value!r}',
                400,
            )
        if quantity < 1:
            raise RefusedRequestError.refusal(
                f'minimum_quantity must be at least one, not {quantity}',
                400,
            )
        return quantity

    def run(self, intent, started_at):
        """Records the order and waits, showing nothing.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 for a bad limit or threshold, and 503 when the instrument has no agreed tick size.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        limit = self.read_limit_price()
        threshold = self.read_minimum_quantity()

        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.remember_tick_size(order)
        self.record_received()
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['placed_quantity'] = 0
        self.save()
        return {
            'broker': None,
            'instrument_id': self.parent.instrument_id,
            'parent_id': self.parent.parent_order_id,
            'tag': self.parent.tag,
            'outcome': 'armed',
            'order_id': None,
            'limit_price': str(limit),
            'minimum_quantity': threshold,
            'status_message': (
                f'the order is recorded and will strike when {threshold} or '
                f'more is showing at {limit} or better'
            ),
            'skipped': [],
        }, 202

    def reachable_quantity(self, view, transaction_type, limit):
        """How much is showing on the other side at a price this order would accept.

        Args:
            view (MarketView): The live quote.
            transaction_type (str): BUY or SELL.
            limit (decimal.Decimal): The worst price allowed.

        Returns:
            int: The total displayed quantity across the levels within the limit.
        """
        if not view.is_readable():
            return 0
        side = 'sell' if transaction_type == 'BUY' else 'buy'
        depth = view.quote.get('depth')
        if not isinstance(depth, dict):
            return 0
        levels = depth.get(side)
        if not isinstance(levels, list):
            return 0
        total = 0
        for entry in levels:
            if not isinstance(entry, dict):
                continue
            price = view.number(entry.get('price'))
            if price is None:
                continue
            if transaction_type == 'BUY' and price > limit:
                continue
            if transaction_type == 'SELL' and price < limit:
                continue
            try:
                total = total + int(entry.get('quantity') or 0)
            except (TypeError, ValueError):
                continue
        return total

    def on_price_tick(self, quotes, now):
        """Strikes when enough size is showing at a price this order will pay.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when an order was sent.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        placed = self.parent.parameters.get('placed_quantity') or 0
        remaining = order.quantity - placed
        if remaining < 1:
            return False

        view = self.view(quotes)
        limit = self.read_limit_price()
        available = self.reachable_quantity(
            view,
            order.transaction_type,
            limit,
        )
        if available < self.read_minimum_quantity():
            return False

        quantity = min(available, remaining)
        price = view.rounded(limit, order.transaction_type)
        if price is None:
            return False

        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['placed_quantity'] = placed + quantity
        self.save()
        return self.strike(order, quantity, price, available)

    def strike(self, order, quantity, price, available):
        """Sends the order that takes what was showing.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            quantity (int): How much to take.
            price (decimal.Decimal): The limit to send it at.
            available (int): How much was showing, for the message.

        Returns:
            bool: True, because an order was sent whatever the broker then said.
        """
        body = dict(self.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body['order_type'] = 'LIMIT'
        body['quantity'] = quantity
        body['transaction_type'] = order.transaction_type
        body['price'] = str(price)
        answer, _, _ = self.place_leg(
            'strike',
            self.read_order(body),
            None,
            self.chosen_broker(),
        )
        if self.parent.state == 'received':
            outcome = answer.get('outcome')
            self.record_state(
                'working' if outcome == 'accepted' else 'failed',
                f'{available} was showing at {price} or better, so {quantity} '
                'went for it',
            )
        self.save()
        return True
