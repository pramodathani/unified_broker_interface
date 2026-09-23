"""Closing the day's positions on your own terms, before the broker closes them on its."""

import decimal
import json

import redis

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder
from unified_broker_interface.utilities.order_engine.utilities.moments import (
    Moments,
)

DEFAULT_BUFFER_TICKS = 2
DEFAULT_PRODUCT = 'intraday'
ORDER_UPDATES_KEY = 'unified:order-updates'
OPEN_STATUSES = (
    'OPEN',
    'TRIGGER_PENDING',
)


class SquareOff(SyntheticOrder):
    """Closes intraday positions at a time of your choosing rather than at the broker's.

    Every broker squares off intraday positions automatically some minutes before the close, and does it the cheapest way for itself: a market order into whatever book is there, plus a fee for the service. Doing it ten minutes earlier, with limit orders, is the same trade at a better price and without the charge.

    `at_time` is when, and it should be comfortably before whatever the broker's own deadline is, because being late means the broker does it and the whole point is lost.

    **Resting orders are cancelled first, and that ordering is not optional.** A stop or a target still live when its position closes will fill afterwards and open a brand new position the other way, unattended, minutes before the close. So every open order on each instrument being closed is cancelled, and only then does the closing order go out.

    What it cancels is scoped to the instruments it is closing, which is the difference between this and `POST /api/orders/flatten`. Flatten is the panic button: it cancels everything at every broker and closes every position, and it is what you want when something has gone wrong. This is the opposite in temperament — a scheduled, ordinary end to a day's trading that leaves overnight positions and their protective orders exactly where they are.

    `instrument_ids` narrows it further to a named set. Without it, every position on the `product` — intraday by default — is closed.
    """

    SYNTHETIC_TYPE = 'square_off'
    WANTS_CLOCK = True

    def run(self, intent, started_at):
        """Records when to close and waits, without sending anything.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when `at_time` is missing or has already passed.
        """
        order = self.read_order(self.parent.body)
        at_time = Moments().time_today(
            self.parent.parameters.get('at_time'),
            'at_time',
        )
        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.remember_tick_size(order)
        self.record_received()
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['close_at'] = at_time
        self.save()
        return {
            'broker': None,
            'instrument_id': self.parent.instrument_id,
            'parent_id': self.parent.parent_order_id,
            'tag': self.parent.tag,
            'outcome': 'scheduled',
            'order_id': None,
            'close_at': self.parent.parameters['at_time'],
            'status_message': (
                f'{self.product()} positions will be closed at '
                f'{self.parent.parameters["at_time"]}'
            ),
            'skipped': [],
        }, 202

    def product(self):
        """Which product's positions are closed.

        This is on the vocabulary the REST API **answers** with — `intraday`, `delivery`, `carryforward` — because that is what the positions document holds, and it is the same convention `QuantityReference` follows for the same reason.

        It is deliberately not the product the closing orders are sent with. That comes from the caller's own body and is on the request vocabulary, `MIS`, `CNC` or `NRML`. The two vocabularies are different in this system and always have been; conflating them here produced "product must be one of CNC, MIS, NRML" from an order built out of a position's own product.

        Returns:
            str: The product to filter positions by.
        """
        return str(
            self.parent.parameters.get('product') or DEFAULT_PRODUCT,
        ).lower()

    def wanted_instruments(self):
        """The instruments to close, or None for every one on the product.

        Returns:
            set | None: The instrument ids, or None when the caller named none.
        """
        given = self.parent.parameters.get('instrument_ids')
        if not given:
            return None
        if not isinstance(given, list):
            raise RefusedRequestError.refusal(
                'instrument_ids must be a list of instrument ids',
                400,
            )
        return set(given)

    def open_positions(self):
        """The positions this square-off is responsible for.

        Returns:
            list: One `(instrument_id, quantity)` per position, quantity signed.
        """
        _, _, positions = self.placement.market_context(
            self.parent.instrument_id,
            False,
            True,
        )
        wanted = self.wanted_instruments()
        found = []
        if not isinstance(positions, dict):
            return found
        for entry in positions.get('net') or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get('product') or '').lower() != self.product():
                continue
            instrument_id = entry.get('instrument_id')
            if not instrument_id:
                continue
            if wanted is not None and instrument_id not in wanted:
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
        """Every open order at every broker on the instruments being closed.

        `unified:order-updates` is a hash keyed `broker:order_id` holding the latest update for every order the whole system has seen, which is exactly the right place to look: it covers orders this engine never placed, including ones sent by hand or by another tool, and those are as capable of re-opening a position as the engine's own.

        Args:
            instrument_ids (set): The instruments being closed.

        Returns:
            list: One `(broker_name, broker_order_id)` per open order.
        """
        found = []
        try:
            stored = self.placement.cache.hgetall(ORDER_UPDATES_KEY)
        except redis.RedisError as error:
            self.logger.error(
                f'The open orders could not be read, so nothing was cancelled '
                f'before squaring off: {error}'
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

    def cancel_resting(self, instrument_ids):
        """Cancels the orders that could re-open a position after it is closed.

        A cancel that a broker refuses is logged and the square-off carries on. Leaving a position open because one stale order could not be cancelled would be the worse mistake: the broker's own square-off is minutes away and will not be so careful.

        Args:
            instrument_ids (set): The instruments being closed.

        Returns:
            int: How many cancels the brokers accepted.
        """
        cancelled = 0
        for broker_name, broker_order_id in self.resting_orders(
            instrument_ids,
        ):
            try:
                answer = self.placement.cancel(broker_name, broker_order_id)
            except RefusedRequestError as refusal:
                self.logger.warning(
                    f'{broker_name} order {broker_order_id} could not be '
                    f'cancelled before squaring off: {refusal.body.get("error")}'
                )
                continue
            if answer.outcome == 'accepted':
                cancelled = cancelled + 1
        return cancelled

    def closing_order(self, instrument_id, quantity):
        """The order that closes one position.

        Args:
            instrument_id (str): The instrument.
            quantity (decimal.Decimal): The net position, signed.

        Returns:
            PlaceOrderRequest | None: The order, or None when the book gives nothing to price against.
        """
        side = 'SELL' if quantity > 0 else 'BUY'
        _, quote, _ = self.placement.market_context(instrument_id, True, False)
        view = self.view({instrument_id: quote})
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
        body['quantity'] = int(abs(quantity))
        body['transaction_type'] = side
        body['price'] = str(price)
        return self.read_order(body)

    def on_clock_tick(self, now):
        """Cancels what is resting and closes what is held, once the time has come.

        Args:
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the square-off ran on this tick.
        """
        close_at = self.parent.parameters.get('close_at')
        if not isinstance(close_at, (int, float)) or now < close_at:
            return False
        if self.parent.parameters.get('squared_off_at') is not None:
            return False
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['squared_off_at'] = now
        self.save()

        positions = self.open_positions()
        if not positions:
            self.record_state(
                'completed',
                f'there were no {self.product()} positions to close',
            )
            self.save()
            return True

        instrument_ids = {instrument_id for instrument_id, _ in positions}
        cancelled = self.cancel_resting(instrument_ids)
        placed = 0
        for instrument_id, quantity in positions:
            order = self.closing_order(instrument_id, quantity)
            if order is None:
                continue
            self.place_leg(
                'close',
                order,
                None,
                self.chosen_broker(),
                instrument_id,
            )
            placed = placed + 1
        self.record_state(
            'working' if placed else 'failed',
            f'{cancelled} resting orders cancelled, {placed} of '
            f'{len(positions)} positions closed',
        )
        self.save()
        return True
