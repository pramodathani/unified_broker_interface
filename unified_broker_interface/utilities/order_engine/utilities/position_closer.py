"""Cancelling what rests on an instrument and closing what is held in it, for the types that close positions they did not open."""

import decimal
import json

import redis

DEFAULT_BUFFER_TICKS = 2
ORDER_UPDATES_KEY = 'unified:order-updates'
OPEN_STATUSES = (
    'OPEN',
    'TRIGGER_PENDING',
)


class PositionCloser:
    """The steps a type takes to close the account's positions: find them, cancel the orders that could re-open them, and build the closing orders.

    **Resting orders are cancelled first, and that ordering is not optional.** A stop or a target still live when its position closes will fill afterwards and open a new position the other way, unattended. Cancelling first also frees the margin those orders hold, which is what lets a closing order through when margin is tight.

    It works through the order type that owns it, so every cancel and every close is recorded on that type's parent and passes its rate budget.

    Attributes:
        runner (SyntheticOrder): The order type doing the closing.
    """

    def __init__(self, runner):
        """Builds the closer for one order type.

        Args:
            runner (SyntheticOrder): The order type doing the closing.

        Returns:
            None: This method returns nothing.
        """
        self.runner = runner

    def open_positions(self, product, wanted_instruments):
        """The net positions held on one product, optionally only in some instruments.

        Args:
            product (str): The product, on the vocabulary the positions document uses, such as `intraday`.
            wanted_instruments (set | None): The instruments to include, or None for every one.

        Returns:
            list: One `(instrument_id, quantity)` per position, quantity signed.
        """
        _, _, positions = self.runner.placement.market_context(
            self.runner.parent.instrument_id,
            False,
            True,
        )
        found = []
        if not isinstance(positions, dict):
            return found
        for entry in positions.get('net') or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get('product') or '').lower() != product:
                continue
            instrument_id = entry.get('instrument_id')
            if not instrument_id:
                continue
            if wanted_instruments is not None and instrument_id not in wanted_instruments:
                continue
            try:
                quantity = decimal.Decimal(str(entry.get('quantity', 0)))
            except (decimal.InvalidOperation, TypeError, ValueError):
                continue
            if quantity == 0:
                continue
            found.append((instrument_id, quantity))
        return found

    def resting_orders(self, instrument_ids):
        """Every open order at every broker on some instruments.

        `unified:order-updates` is a hash keyed `broker:order_id` holding the latest update for every order the whole system has seen. It covers orders this engine never placed, including ones sent by hand or by another tool, and those are as capable of re-opening a position as the engine's own.

        Args:
            instrument_ids (set): The instruments.

        Returns:
            list: One `(broker_name, broker_order_id)` per open order.
        """
        found = []
        try:
            stored = self.runner.placement.cache.hgetall(ORDER_UPDATES_KEY)
        except redis.RedisError as error:
            self.runner.logger.error(
                f'The open orders could not be read, so nothing was cancelled '
                f'before closing: {error}'
            )
            return found
        for document in (stored or {}).values():
            try:
                order = json.loads(document)
            except (TypeError, ValueError):
                continue
            if not isinstance(order, dict):
                continue
            if order.get('instrument_id') not in instrument_ids:
                continue
            if order.get('status') not in OPEN_STATUSES:
                continue
            broker = order.get('broker')
            order_id = order.get('order_id')
            if broker and order_id:
                found.append((broker, str(order_id)))
        return found

    def cancel_resting(self, instrument_ids, reason):
        """Cancels the orders that could re-open a position after it is closed.

        A cancel that a broker refuses is recorded and the closing carries on. Leaving a position open because one stale order could not be cancelled would be the worse mistake.

        Args:
            instrument_ids (set): The instruments being closed.
            reason (str): Why, for a person reading the parent later.

        Returns:
            int: How many cancels the brokers accepted.
        """
        cancelled = 0
        for broker_name, broker_order_id in self.resting_orders(instrument_ids):
            accepted = self.runner.cancel_outside_order(
                broker_name,
                broker_order_id,
                reason,
            )
            if accepted:
                cancelled = cancelled + 1
        return cancelled

    def closing_order(self, instrument_id, quantity):
        """The limit order that closes one position, priced two ticks past the other side's best price.

        Args:
            instrument_id (str): The instrument.
            quantity (decimal.Decimal): The net position, signed.

        Returns:
            PlaceOrderRequest | None: The order, or None when the book gives nothing to price against.
        """
        side = 'SELL' if quantity > 0 else 'BUY'
        _, quote, _ = self.runner.placement.market_context(
            instrument_id,
            True,
            False,
        )
        view = self.runner.view({instrument_id: quote})
        touch = view.opposite_touch(side)
        if touch is None:
            touch = view.last()
        if touch is None:
            return None
        price = view.moved(touch, DEFAULT_BUFFER_TICKS, side, True)
        price = view.rounded(price, side)
        if price is None or price <= 0:
            return None
        body = dict(self.runner.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body.pop('synthetic', None)
        body['order_type'] = 'LIMIT'
        body['quantity'] = int(abs(quantity))
        body['transaction_type'] = side
        body['price'] = str(price)
        return self.runner.read_order(body)
