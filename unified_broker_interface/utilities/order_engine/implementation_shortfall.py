"""An order that does most of its trading early, to stay near the price it decided at."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.twap import Twap

MOST_DECAY = 0.5


class ImplementationShortfall(Twap):
    """A sliced order whose slices get smaller, so most of it trades near the price it started from.

    Implementation shortfall is the gap between the price when somebody decided to trade and the price they actually got. It has two halves that pull against each other. Trading everything at once pays the whole spread and moves the book, which is **impact**. Trading slowly avoids that but leaves the order exposed to the market simply walking away, which is **drift**. A time-weighted order treats those two as equally important all the way through. This one does not: it front-loads, because drift compounds with time and impact does not.

    `urgency` is the dial, from 0 to 1. At 0 every slice is the same size and this is exactly a time-weighted order. At 1 each slice is half the one before it, so a ten-slice order has done half its trading in the first two slices and is trickling out the tail. In between, a slice is `1 - urgency / 2` of the previous one.

    A geometric decay rather than anything more elaborate, because the shape is the point and the exact curve is not. What matters is that more happens early, that the dial is monotonic, and that somebody reading the number can work out what it will do.

    The arrival price — the market when the order was accepted — is recorded on the parent, so the shortfall this was built to minimise can actually be measured afterwards rather than assumed.
    """

    SYNTHETIC_TYPE = 'implementation_shortfall'

    def read_urgency(self):
        """How much more the early slices take than the late ones.

        Returns:
            float: The urgency, between zero and one.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a number in that range.
        """
        value = self.parent.parameters.get('urgency', 0.5)
        try:
            urgency = float(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'urgency must be a number between 0 and 1, not {value!r}',
                400,
            )
        if urgency < 0 or urgency > 1:
            raise RefusedRequestError.refusal(
                f'urgency must be between 0 and 1, not {urgency}',
                400,
            )
        return urgency

    def slice_weights(self, slices):
        """The share of the order each slice takes, falling away geometrically.

        Args:
            slices (int): How many slices there are.

        Returns:
            list: One weight per slice, each a fixed fraction of the one before.
        """
        decay = 1 - self.read_urgency() * MOST_DECAY
        weights = []
        weight = 1.0
        for _ in range(slices):
            weights.append(weight)
            weight = weight * decay
        return weights

    def run(self, intent, started_at):
        """Records the price the order arrived at, then slices it as a timed order does.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For an order answered without calling a broker.
        """
        self.read_urgency()
        self.remember_arrival_price()
        return super().run(intent, started_at)

    def remember_arrival_price(self):
        """Keeps the market's last price at the moment the order was accepted.

        This is the number the whole type is measured against afterwards, and it is only available now. A quote that cannot be read is not a reason to refuse the order — the slicing works either way — so it is recorded as absent rather than raised.

        Returns:
            None: This method returns nothing.
        """
        try:
            _, quote, _ = self.placement.market_context(
                self.parent.instrument_id,
                True,
                False,
            )
        except RefusedRequestError:
            quote = None
        self.parent.parameters = dict(self.parent.parameters)
        price = None
        if isinstance(quote, dict):
            price = quote.get('last_price')
        self.parent.parameters['arrival_price'] = price
