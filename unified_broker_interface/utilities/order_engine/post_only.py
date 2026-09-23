"""A limit order that refuses to take liquidity, checked before it is sent."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder


class PostOnly(SyntheticOrder):
    """A limit that is only worth sending if it will rest rather than trade.

    Crypto venues have this as a real order type, and it is a real guarantee there: the exchange rejects the order outright rather than let it cross. Indian exchanges have no such flag, so this is the honest approximation and the Atlas says so plainly — the price is checked against the book before the order goes, and the book can move while the order is in flight, so an order that was passive when it left can still take liquidity when it lands.

    What it is for is usually fees and queue position rather than price. An order that rests is an order other people trade against, which is where a maker's edge comes from; an order that crosses pays the spread and gives that edge away. Somebody working a large position through the day cares about the difference far more than about any one fill.

    A buy is passive at or below the best bid and a sell at or above the best offer. A price on the wrong side of that is not quietly corrected by default, because quietly correcting it would fill the caller's order at a price they did not ask for, which is precisely the thing the type exists to avoid. `on_crossing` says what to do instead: `refuse` is the default and answers 409 with the book that refused it, and `rest` moves the price back to the touch and sends it there.

    This does not watch the market afterwards. A resting order that the market later comes up to is an order being traded against, which is the whole point; pulling it away would be a peg, and `peg` is that type.
    """

    SYNTHETIC_TYPE = 'post_only'

    def read_on_crossing(self):
        """What to do with a price that would take liquidity.

        Returns:
            str: `refuse` or `rest`.

        Raises:
            RefusedRequestError: With HTTP 400 when the caller named something else.
        """
        choice = self.parent.parameters.get('on_crossing', 'refuse')
        if choice not in ('refuse', 'rest'):
            raise RefusedRequestError.refusal(
                f'on_crossing must be refuse or rest, not {choice!r}',
                400,
            )
        return choice

    def would_cross(self, price, transaction_type, view):
        """Whether an order at this price would trade immediately against what is resting.

        Args:
            price (decimal.Decimal): The price the caller asked for.
            transaction_type (str): BUY or SELL.
            view (MarketView): The live quote.

        Returns:
            bool: True when the order would take liquidity.
        """
        touch = view.opposite_touch(transaction_type)
        if touch is None:
            return False
        if transaction_type == 'BUY':
            return price >= touch
        return price <= touch

    def run(self, intent, started_at):
        """Checks the price against the book, then sends the order or refuses it.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 for a bad `on_crossing`, 409 when the price would cross and the caller asked to be refused, and 503 when there is no tick size or no quote to check against.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        self.read_on_crossing()

        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.remember_tick_size(order)
        _, quote, _ = self.placement.market_context(
            self.parent.instrument_id,
            True,
            False,
        )
        view = self.view({self.parent.instrument_id: quote})
        own = view.own_touch(order.transaction_type)
        if not view.is_readable() or own is None:
            raise RefusedRequestError.refusal(
                'a post-only order is checked against the book before it is '
                'sent and the live quote does not carry the book yet',
                503,
                instrument_id=self.parent.instrument_id,
            )

        price = order.price
        if self.would_cross(price, order.transaction_type, view):
            if self.read_on_crossing() == 'refuse':
                raise RefusedRequestError.refusal(
                    f'a post-only {order.transaction_type} at {price} would '
                    f'take liquidity against a book of {view.best_bid()} bid '
                    f'and {view.best_offer()} offered, so nothing was sent',
                    409,
                    instrument_id=self.parent.instrument_id,
                )
            price = own

        self.record_received()
        self.save()
        body, status, _ = self.place_leg(
            'entry',
            self.priced(order, price),
            started_at,
        )
        outcome = body.get('outcome')
        state = {
            'accepted': 'working',
            'rejected': 'rejected',
        }.get(outcome, 'failed')
        self.record_state(state, body.get('status_message'))
        self.save()
        body['parent_id'] = self.parent.parent_order_id
        return body, status

    def priced(self, order, price):
        """The order at the price that was checked, which may not be the one asked for.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            price (decimal.Decimal): The price to send.

        Returns:
            PlaceOrderRequest: The order to place.
        """
        body = dict(self.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body['order_type'] = 'LIMIT'
        body['quantity'] = order.quantity
        body['transaction_type'] = order.transaction_type
        body['price'] = str(price)
        return self.read_order(body)
