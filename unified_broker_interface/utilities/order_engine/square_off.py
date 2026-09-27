"""Closing the day's positions on your own terms, before the broker closes them on its."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder
from unified_broker_interface.utilities.order_engine.utilities.moments import (
    Moments,
)
from unified_broker_interface.utilities.order_engine.utilities.position_closer import (
    PositionCloser,
)

DEFAULT_PRODUCT = 'intraday'


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

        closer = PositionCloser(self)
        positions = closer.open_positions(
            self.product(),
            self.wanted_instruments(),
        )
        if not positions:
            self.record_state(
                'completed',
                f'there were no {self.product()} positions to close',
            )
            self.save()
            return True

        instrument_ids = {instrument_id for instrument_id, _ in positions}
        cancelled = closer.cancel_resting(
            instrument_ids,
            'cancelled before squaring off, so it cannot re-open the position',
        )
        placed = 0
        for instrument_id, quantity in positions:
            order = closer.closing_order(instrument_id, quantity)
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
