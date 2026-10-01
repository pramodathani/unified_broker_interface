"""Cancelling what rests on an instrument and closing what is held in it, for the types that close positions they did not open."""

import decimal
import json

import redis

from unified_broker_interface.utilities.broker_orders.utilities.kill_switch import (
    KillSwitch,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.reduce_only import (
    POSITION_PRODUCTS,
)

BROKER_TOKENS_KEY = 'unified:broker_tokens'
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
        """The net positions held on one product at each broker, optionally only in some instruments.

        Each broker's own `<broker>:portfolio:positions` is read, rather than the unified positions document, because that document merges a position across brokers and a closing order has to go to the broker that actually holds it. They are read through `KillSwitch`, exactly as `POST /api/orders/flatten` reads them.

        A position whose broker token does not name exactly one instrument today cannot be priced or placed through the engine. It is listed with an instrument of None when every instrument was asked for, so the caller can report it, and left out when only some instruments were asked for.

        Args:
            product (str): The product, on the vocabulary the positions document uses, such as `intraday`.
            wanted_instruments (set | None): The instruments to include, or None for every one.

        Returns:
            list: One `(broker_name, instrument_id, quantity)` per position, where `broker_name` is a string, `instrument_id` a string or None, and `quantity` a signed decimal.Decimal.
        """
        broker_names = self.runner.placement.order_placement.broker_names
        position_books = self.position_books(broker_names)
        found = []
        for position in KillSwitch(broker_names).positions_to_close(position_books):
            position_product = POSITION_PRODUCTS.get(
                str(position.get('product') or '').upper(),
            )
            if position_product != product:
                continue
            instrument_id = self.instrument_for_broker_token(
                position['broker'],
                position.get('instrument_token'),
            )
            if wanted_instruments is not None and instrument_id not in wanted_instruments:
                continue
            found.append((
                position['broker'],
                instrument_id,
                decimal.Decimal(position['quantity']),
            ))
        return found

    def position_books(self, broker_names):
        """Each broker's positions hash, decoded, by broker name.

        Args:
            broker_names (list): The brokers to read, in order.

        Returns:
            dict: Broker names to their decoded entries, empty when Redis cannot be read.
        """
        try:
            pipeline = self.runner.placement.cache.pipeline(transaction=False)
            for broker_name in broker_names:
                pipeline.hgetall(f'{broker_name}:portfolio:positions')
            replies = pipeline.execute()
        except redis.RedisError as error:
            self.runner.logger.error(
                f'The brokers\' positions could not be read, so nothing was closed: {error}'
            )
            return {}
        books = {}
        for index, broker_name in enumerate(broker_names):
            decoded = {}
            for key, text in (replies[index] or {}).items():
                try:
                    entry = json.loads(text)
                except (TypeError, ValueError):
                    continue
                if isinstance(entry, dict):
                    decoded[key] = entry
            books[broker_name] = decoded
        return books

    def instrument_for_broker_token(self, broker_name, broker_token):
        """The one instrument a broker's token names today, or None when it is not exactly one.

        Args:
            broker_name (str): The broker.
            broker_token (str | None): The broker's own instrument token.

        Returns:
            str | None: The instrument id.
        """
        if not broker_token:
            return None
        try:
            stored = self.runner.placement.cache.hget(
                BROKER_TOKENS_KEY,
                f'{broker_name}:{broker_token}',
            )
        except redis.RedisError:
            return None
        if not stored:
            return None
        try:
            instrument_ids = json.loads(stored)
        except (TypeError, ValueError):
            return None
        if not isinstance(instrument_ids, list) or len(instrument_ids) != 1:
            return None
        return str(instrument_ids[0])

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

        The price is rounded with the tick size the brokers agree on for that instrument, which is not always the parent's own.

        Args:
            instrument_id (str): The instrument.
            quantity (decimal.Decimal): The net position, signed.

        Returns:
            PlaceOrderRequest | None: The order, or None when the book gives nothing to price against or the instrument has no agreed tick size.
        """
        side = 'SELL' if quantity > 0 else 'BUY'
        instrument, quote, _ = self.runner.placement.market_context(
            instrument_id,
            True,
            False,
        )
        template = self.runner.read_order(self.runner.parent.body)
        tick_size = template.agreed_tick_size(instrument.handles)
        if tick_size is None:
            return None
        view = MarketView(quote, tick_size)
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
