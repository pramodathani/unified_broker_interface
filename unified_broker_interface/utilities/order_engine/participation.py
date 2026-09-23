"""An order that trades a fixed share of whatever the market itself trades."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder

DEFAULT_BUFFER_TICKS = 2


class Participation(SyntheticOrder):
    """A sliced order that keeps its own trading to `participation_percent` of the market's.

    Also called a percentage-of-volume order. The idea is the most direct answer there is to the question a large order has to ask: how much can I trade without being noticed? However much everybody else is trading, times a small fraction.

    It is the adaptive cousin of the time-weighted and volume-weighted types, and the difference is worth being clear about. A time-weighted order sends the same size every interval whatever happens. A volume-weighted order sends sizes decided in advance from what a normal day looks like. This one decides nothing in advance: it looks at how much has actually traded since its last slice and sends that fraction of it. On a day when news arrives at eleven o'clock it speeds up; on a dead afternoon it almost stops.

    The cost is that it has no deadline. A percentage-of-volume order in a market that stops trading stops trading too, and can finish the day with most of the order undone. `most_slices` bounds how many orders it will send, and the caller is expected to watch it, or to wrap it in a time stop.

    The measurement is the quote's own cumulative `volume` field, and the difference between one tick and the next is what traded in between. That is simpler and more reliable than trying to count trades, and it is the same number the exchange publishes.

    A slice smaller than one unit is not sent. It is remembered instead: the volume that earned it stays uncounted, so a slow market accumulates until it is worth one order rather than sending nothing for ever.
    """

    SYNTHETIC_TYPE = 'participation'
    WANTS_PRICES = True

    def read_percent(self):
        """What share of the market's volume this order takes.

        Returns:
            float: The percentage, above zero and at most one hundred.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or out of range.
        """
        value = self.parent.parameters.get('participation_percent')
        if value is None:
            raise RefusedRequestError.refusal(
                'a participation order needs participation_percent, the share '
                "of the market's volume it takes",
                400,
            )
        try:
            percent = float(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'participation_percent must be a number, not {value!r}',
                400,
            )
        if percent <= 0 or percent > 100:
            raise RefusedRequestError.refusal(
                f'participation_percent must be above zero and at most 100, '
                f'not {percent}',
                400,
            )
        return percent

    def read_most_slices(self):
        """How many orders this will send before it stops.

        Returns:
            int: The limit.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a whole number above zero.
        """
        value = self.parent.parameters.get('most_slices', 60)
        try:
            most = int(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'most_slices must be a whole number, not {value!r}',
                400,
            )
        if most < 1:
            raise RefusedRequestError.refusal(
                f'most_slices must be at least one, not {most}',
                400,
            )
        return most

    def run(self, intent, started_at):
        """Records the order and the market's volume so far, then waits for the market to trade.

        Nothing is sent now. The first slice is a share of volume that has not happened yet, so there is nothing to take a share of until the next tick.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 for a bad percentage, and 503 when there is no tick size or no quote to start counting from.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        percent = self.read_percent()
        self.read_most_slices()

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
        volume = self.volume_of(quote)
        if volume is None:
            raise RefusedRequestError.refusal(
                "a participation order measures the market's volume and the "
                'live quote does not carry it yet',
                503,
                instrument_id=self.parent.instrument_id,
            )

        self.record_received()
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['counted_volume'] = volume
        self.parent.parameters['placed_quantity'] = 0
        self.save()
        return {
            'broker': None,
            'instrument_id': self.parent.instrument_id,
            'parent_id': self.parent.parent_order_id,
            'tag': self.parent.tag,
            'outcome': 'armed',
            'order_id': None,
            'participation_percent': percent,
            'status_message': (
                f'the order is recorded and will trade {percent} per cent of '
                'whatever the market trades from now on'
            ),
            'skipped': [],
        }, 202

    def volume_of(self, quote):
        """The day's cumulative traded volume out of a quote.

        Args:
            quote (dict | None): The instrument's quote.

        Returns:
            int | None: The volume, or None when the quote does not carry a usable one.
        """
        if not isinstance(quote, dict):
            return None
        value = quote.get('volume')
        try:
            volume = int(value)
        except (TypeError, ValueError):
            return None
        if volume < 0:
            return None
        return volume

    def on_price_tick(self, quotes, now):
        """Sends a share of whatever has traded since the last slice.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when a slice was sent.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        placed = self.parent.parameters.get('placed_quantity') or 0
        remaining = order.quantity - placed
        if remaining < 1:
            return False
        if len(self.parent.legs) >= self.read_most_slices():
            return False

        view = self.view(quotes)
        volume = self.volume_of(self.own_quote(quotes))
        counted = self.parent.parameters.get('counted_volume')
        if volume is None or not isinstance(counted, int):
            return False
        traded = volume - counted
        if traded <= 0:
            return False

        share = int(traded * self.read_percent() / 100)
        if share < 1:
            return False
        quantity = min(share, remaining)
        price = self.marketable_price(view, order.transaction_type)
        if price is None:
            return False

        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['counted_volume'] = volume
        self.parent.parameters['placed_quantity'] = placed + quantity
        self.save()
        return self.send_slice(order, quantity, price, traded)

    def marketable_price(self, view, transaction_type):
        """The price a slice is sent at, past the touch so that it trades now.

        Args:
            view (MarketView): The live quote.
            transaction_type (str): BUY or SELL.

        Returns:
            decimal.Decimal | None: The price, or None when the book has no opposite side.
        """
        touch = view.opposite_touch(transaction_type)
        if touch is None:
            return None
        price = view.moved(
            touch,
            DEFAULT_BUFFER_TICKS,
            transaction_type,
            True,
        )
        price = view.rounded(price, transaction_type)
        if price is None or price <= 0:
            return None
        return price

    def send_slice(self, order, quantity, price, traded):
        """Sends one slice and records what the parent became.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            quantity (int): How much this slice carries.
            price (decimal.Decimal): The price to send.
            traded (int): How much the market traded to earn this slice, for the message.

        Returns:
            bool: True, because a slice was sent whatever the broker then said.
        """
        body = dict(self.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body['order_type'] = 'LIMIT'
        body['quantity'] = quantity
        body['transaction_type'] = order.transaction_type
        body['price'] = str(price)
        answer, _, _ = self.place_leg(
            'slice',
            self.read_order(body),
            None,
            self.chosen_broker(),
        )
        if self.parent.state == 'received':
            outcome = answer.get('outcome')
            self.record_state(
                'working' if outcome == 'accepted' else 'failed',
                f'the market traded {traded}, so {quantity} went out with it',
            )
        self.save()
        return True
