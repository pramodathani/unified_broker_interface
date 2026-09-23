"""An order on one instrument, triggered by the price of another."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.limit_if_touched import (
    LimitIfTouched,
)


class CrossInstrument(LimitIfTouched):
    """A limit-if-touched order whose trigger watches something it does not trade.

    This is the type that cannot exist at an exchange at all. A native stop watches its own instrument's last traded price and nothing else, so an order on a Nifty option can only be triggered by that option's own premium.

    That is often exactly the wrong thing to watch. A far out-of-the-money strike trades a few hundred times a day, its premium can double on one small order going through a thin book, and a stop on the premium is stopped out by the book rather than by the market. The index itself trades continuously and cannot be moved that way. So: hold the option, watch the index, and exit the option when the index crosses the level that actually invalidates the trade.

    `watch_instrument_id` names the instrument to watch. It is read by the price ticker as well as by this class, because the ticker has to know which quotes to fetch before it builds anything, so the parameter is read by name rather than asked of the class.

    The pairing is not checked. Nothing here verifies that the watched instrument is the traded one's underlying, or related to it at all, because there is no relationship the engine could confirm and plenty of useful pairs that are not underlyings: a calendar spread's near leg watching the far one, a stock watching its sector index, a commodity watching the dollar. The caller says what to watch and the engine watches it.
    """

    SYNTHETIC_TYPE = 'cross_instrument'
    ARMED_MESSAGE = 'the watched instrument touches the level'

    def watched_instrument(self):
        """The instrument whose price this trigger reads, which is not the one it trades.

        Returns:
            str: The instrument id.

        Raises:
            RefusedRequestError: With HTTP 400 when the caller did not name one.
        """
        watched = self.parent.parameters.get('watch_instrument_id')
        if not watched:
            raise RefusedRequestError.refusal(
                'a cross-instrument order is triggered by another '
                "instrument's price, so it needs watch_instrument_id",
                400,
            )
        return watched

    def run(self, intent, started_at):
        """Records the order, refusing early if there is no instrument to watch.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when the watched instrument, the trigger or the limit price cannot be read.
        """
        self.watched_instrument()
        return super().run(intent, started_at)
