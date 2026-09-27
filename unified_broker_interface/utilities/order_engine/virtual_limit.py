"""A limit order kept in the engine's own book, and sent to a broker only once it will fill."""

import json

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.price_trigger import (
    PriceTrigger,
)
from unified_broker_interface.utilities.order_engine.utilities.virtual_book import (
    ESTIMATES_KEY,
)


class VirtualLimit(PriceTrigger):
    """A limit order held in the synthetic limit order book instead of resting at the exchange.

    A resting limit order that never fills spends two of a broker's daily order messages, one to place it and one to cancel it, and at Zerodha, once 5,000 have been spent, not even an exit can be placed. This order spends one, and only when it will fill. It is held by the engine and sent, as a limit at the caller's own price, once the other side of the book reaches that price: for a buy, when the best offer is at or below it. An order sent then takes the offer and fills straight away, at the caller's price or better.

    What that gives up is the place in the queue. A resting order also fills when sellers come down and hit the bids at its price, even if the offer never reaches it. `bin/unified/orders/virtual_book` follows every held order through the quote stream and estimates how much such a resting order would have filled. When this order is sent, that estimate is recorded as `missed_quantity`: the cost of having held it back.

    With `paper: true` nothing is ever sent. The order is filled from the same estimate, as it would have been had it been resting at the exchange: partly as the queue ahead of it trades away, and wholly once the other side reaches its price. Paper fills are recorded as `paper_filled` events at the order's limit price, and the parent completes when the whole quantity has filled.

    A quote marked stale is never acted on, since the book it describes may no longer exist. A held order lasts for the trading day, like a DAY limit at the exchange, and survives an engine restart within the day through the event log.

    The limit price is the order's own `price`, so the body is an ordinary limit order with `synthetic: {"type": "virtual_limit"}` added.
    """

    SYNTHETIC_TYPE = 'virtual_limit'
    ARMED_MESSAGE = 'the other side of the book reaches the limit price'
    TAKES_TRIGGER_ON = False

    def is_paper(self):
        """Whether this order is filled from the queue estimate instead of being sent.

        Returns:
            bool: True for a paper order.
        """
        return self.parent.parameters.get('paper') is True

    def held_order(self):
        """The order as it is held now: the caller's body, with any price and quantity changed since through `PUT /api/orders/modify`.

        Returns:
            PlaceOrderRequest: The held order.
        """
        body = dict(self.parent.body)
        held_price = self.parent.parameters.get('held_price')
        if held_price is not None:
            body['price'] = held_price
        held_quantity = self.parent.parameters.get('held_quantity')
        if held_quantity is not None:
            body['quantity'] = held_quantity
        return self.read_order(body)

    def read_level(self):
        """The order's limit price, which is also the price the other side has to reach.

        Returns:
            decimal.Decimal: The limit price.

        Raises:
            RefusedRequestError: With HTTP 400 when the order is not a limit order with a price.
        """
        order = self.held_order()
        if order.order_type != 'LIMIT' or order.price is None:
            raise RefusedRequestError.refusal(
                'a virtual limit order is held at its own limit price, so it '
                'must be a LIMIT order with a price',
                400,
            )
        return order.price

    def watched_price(self, view):
        """The best price on the other side of the book, unless the quote is stale.

        Args:
            view (MarketView): The instrument's quote.

        Returns:
            decimal.Decimal | None: The offer for a buy or the bid for a sell, or None when it cannot be trusted.
        """
        if view.is_stale():
            return None
        transaction_type = self.parent.body.get('transaction_type')
        return view.opposite_touch(transaction_type)

    def child_order(self, order, view):
        """A limit at the order's own price.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            view (MarketView): The instrument's quote at the moment it fired.

        Returns:
            PlaceOrderRequest: The order to place, at the held price and quantity.
        """
        return self.priced(self.held_order(), self.read_level())

    def run(self, intent, started_at):
        """Records the order and holds it, refusing early if it is not a limit order.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a limit order with a price, and 503 when the instrument has no agreed tick size.
        """
        self.read_level()
        body, status = super().run(intent, started_at)
        if status == 202:
            body['paper'] = self.is_paper()
        return body, status

    def estimate(self):
        """What `virtual_book` last worked out about this order's place in the queue, or None.

        Returns:
            dict | None: The stored estimate.
        """
        try:
            stored = self.placement.cache.hget(
                ESTIMATES_KEY,
                self.parent.parent_order_id,
            )
        except Exception as error:
            self.logger.warning(
                f'The queue estimate for {self.parent.parent_order_id} could '
                f'not be read: {error}'
            )
            return None
        if not stored:
            return None
        try:
            document = json.loads(stored)
        except ValueError:
            return None
        if not isinstance(document, dict):
            return None
        return document

    def fire(self, child, price, level):
        """Sends the order, first recording how much a resting order would have filled while this one was held.

        Args:
            child (PlaceOrderRequest): The order to place.
            price (decimal.Decimal): The price on the other side that reached the level.
            level (decimal.Decimal): The limit price.

        Returns:
            bool: True, because the order was sent whatever the broker then said.
        """
        estimate = self.estimate() or {}
        missed = estimate.get('queue_filled')
        if isinstance(missed, int):
            self.parent.parameters = dict(self.parent.parameters)
            self.parent.parameters['missed_quantity'] = missed
            self.save()
        return super().fire(child, price, level)

    def on_price_tick(self, quotes, now):
        """Sends a held order once the other side reaches its price, or fills a paper order from the queue estimate.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the order was sent or a paper fill was recorded on this tick.
        """
        if self.is_paper():
            return self.fill_on_paper()
        return super().on_price_tick(quotes, now)

    def fill_on_paper(self):
        """Records whatever more the queue estimate says a resting order would have filled.

        Returns:
            bool: True when a fill was recorded.
        """
        if self.parent.is_terminal():
            return False
        estimate = self.estimate()
        if estimate is None:
            return False
        filled = estimate.get('filled')
        if not isinstance(filled, int):
            return False
        order = self.held_order()
        filled = min(filled, order.quantity)
        already = self.parent.parameters.get('paper_filled') or 0
        if filled <= already:
            return False
        self.record({
            'event': 'paper_filled',
            'parent_state': self.parent.state,
            'transaction_type': order.transaction_type,
            'quantity': order.quantity,
            'filled_quantity': filled,
            'price': self.json_number(self.read_level()),
            'detail': {
                'estimate': estimate,
            },
        })
        if self.parent.state == 'received':
            self.record_state(
                'working',
                f'paper fill of {filled} of {order.quantity}',
            )
        if filled >= order.quantity:
            self.record_state(
                'completed',
                f'filled on paper: {filled} at {self.read_level()}',
            )
        self.save()
        return True

    def modify_held(self, price, quantity, dry_run):
        """Changes the price or quantity of the order while it is still held, without sending anything to a broker.

        The change is recorded with the parameters, so a restart keeps it, and `virtual_book` starts a fresh queue estimate for the new terms, as a changed price at the exchange goes to the back of the queue.

        Args:
            price (decimal.Decimal | None): The new limit price, or None to keep it.
            quantity (int | None): The new quantity in units, or None to keep it.
            dry_run (bool): Whether to check the change without making it.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 409 when the order has already been sent or has finished, or a paper order would be cut below what it has filled; 400 when the price is not a whole number of ticks or the quantity is not a whole number of lots at any broker.
        """
        if self.parent.is_terminal():
            raise RefusedRequestError.refusal(
                f'the order is already {self.parent.state}',
                409,
                parent_id=self.parent.parent_order_id,
            )
        if self.has_fired():
            sent = None
            for leg in self.parent.legs:
                if leg.role != 'backstop':
                    sent = leg
            detail = {
                'parent_id': self.parent.parent_order_id,
            }
            if sent is not None:
                detail['broker'] = sent.broker
                detail['order_id'] = sent.broker_order_id
            raise RefusedRequestError.refusal(
                'the order has already been sent to a broker, so change it '
                'with broker and order_id instead of parent_id',
                409,
                **detail,
            )
        current = self.held_order()
        new_price = price if price is not None else current.price
        new_quantity = quantity if quantity is not None else current.quantity
        body = dict(self.parent.body)
        body['price'] = str(new_price)
        body['quantity'] = new_quantity
        changed = self.read_order(body)
        tick_size = self.tick_size()
        if tick_size and changed.price % tick_size != 0:
            raise RefusedRequestError.refusal(
                f'price must be a whole number of ticks of '
                f'{format(tick_size.normalize(), "f")}',
                400,
            )
        instrument, _, _ = self.placement.market_context(
            self.parent.instrument_id,
            False,
            False,
        )
        problems = []
        for handle in (instrument.handles or {}).values():
            problems.append(changed.lot_size_problem(handle))
        if problems and all(problems):
            raise RefusedRequestError.refusal(problems[0], 400)
        filled = self.parent.parameters.get('paper_filled') or 0
        if new_quantity <= filled:
            raise RefusedRequestError.refusal(
                f'the paper order has already filled {filled}, so its '
                f'quantity cannot become {new_quantity}',
                409,
                parent_id=self.parent.parent_order_id,
            )
        answer = {
            'parent_id': self.parent.parent_order_id,
            'synthetic_type': self.parent.synthetic_type,
            'held': True,
            'price': str(changed.price),
            'quantity': changed.quantity,
        }
        if dry_run:
            answer['dry_run'] = True
            answer['status_message'] = 'the change is valid; nothing was changed'
            return answer, 200
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['held_price'] = str(changed.price)
        self.parent.parameters['held_quantity'] = changed.quantity
        self.record_parameters(
            f'the caller changed the held order to {changed.quantity} at '
            f'{changed.price}'
        )
        self.save()
        answer['outcome'] = 'accepted'
        answer['status_message'] = (
            'changed while held in the virtual order book; nothing was sent '
            'to a broker'
        )
        return answer, 200
