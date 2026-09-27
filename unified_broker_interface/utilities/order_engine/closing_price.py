"""An order sliced through the window the closing price is computed from, so it pays close to that price."""

import datetime

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.moments import (
    Moments,
)
from unified_broker_interface.utilities.order_engine.vwap import Vwap

DEFAULT_WINDOW_START = '15:00'
DEFAULT_SLICES = 6
WINDOW_ENDS_AT = datetime.time(15, 30)
EARLIEST_WINDOW_START = datetime.time(9, 15)


class ClosingPrice(Vwap):
    """A volume-weighted order spread across the last half hour, the Atlas's G2 (market-on-close or limit-on-close).

    NSE and BSE compute an equity's closing price as the volume weighted average of trades from 15:00 to 15:30, so an order that trades in proportion to volume through that window pays close to the closing price by construction. The cash segment's post-closing session fills market orders at the closing price exactly, but only for delivery products; for futures, options and intraday orders this is the nearest there is.

    Before the window opens the order answers `202 scheduled` and places nothing, and `Twap`'s clock sends the first slice when the window starts. An order that arrives inside the window starts at once and spreads what is left of it, and one that arrives after 15:30 is refused. The slices are weighted by `Vwap`'s volume profile, whose last two buckets are the heaviest of the day.
    """

    SYNTHETIC_TYPE = 'closing_price'

    def read_window_start(self, now):
        """When the slicing window opens today.

        Args:
            now (datetime.datetime): Now, in India.

        Returns:
            datetime.datetime: The start, today.

        Raises:
            RefusedRequestError: With HTTP 400 when `window_start` is not a time from 09:15 and before 15:30.
        """
        text = self.parent.parameters.get('window_start') or DEFAULT_WINDOW_START
        try:
            wanted = datetime.time.fromisoformat(str(text))
        except ValueError:
            raise RefusedRequestError.refusal(
                f'window_start must be a time of day such as 15:00, not '
                f'{text!r}',
                400,
            )
        if wanted < EARLIEST_WINDOW_START or wanted >= WINDOW_ENDS_AT:
            raise RefusedRequestError.refusal(
                f'window_start must be from {EARLIEST_WINDOW_START} and before '
                f'{WINDOW_ENDS_AT}, not {text}',
                400,
            )
        return self.moment_today(wanted, now)

    def moment_today(self, wanted, now):
        """A time of day today, as a moment in India.

        Args:
            wanted (datetime.time): The time of day.
            now (datetime.datetime): Now, in India.

        Returns:
            datetime.datetime: That time today.
        """
        return now.replace(
            hour=wanted.hour,
            minute=wanted.minute,
            second=wanted.second,
            microsecond=0,
        )

    def run(self, intent, started_at):
        """Records the schedule, and sends the first slice now when the window is already open.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 for a bad window or slice count, when `over_minutes` is given, and when the window has already closed today.
        """
        if self.parent.parameters.get('over_minutes') is not None:
            raise RefusedRequestError.refusal(
                'a closing_price order works out its own duration from the '
                'window, so it does not take over_minutes',
                400,
            )
        now = Moments().now()
        window_start = self.read_window_start(now)
        window_end = self.moment_today(WINDOW_ENDS_AT, now)
        if now >= window_end:
            raise RefusedRequestError.refusal(
                f'the closing price window ended at {WINDOW_ENDS_AT} today',
                400,
            )
        begins = max(now, window_start)
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters.setdefault('slices', DEFAULT_SLICES)
        self.parent.parameters['over_minutes'] = (
            (window_end - begins).total_seconds() / 60
        )
        if now >= window_start:
            return super().run(intent, started_at)

        order = self.concrete_order(self.read_order(self.parent.body))
        slices, over_minutes = self.schedule(order)
        if order.dry_run:
            prepared = self.placement.prepare(
                self.slice_order(order, slices, 0),
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.parent.parameters['slice_count'] = slices
        self.parent.parameters['interval_seconds'] = over_minutes * 60 / slices
        self.parent.parameters['started_at'] = window_start.timestamp()
        self.record_received()
        self.save()
        place_at = window_start.strftime('%H:%M:%S')
        return {
            'broker': None,
            'instrument_id': self.parent.instrument_id,
            'parent_id': self.parent.parent_order_id,
            'tag': self.parent.tag,
            'outcome': 'scheduled',
            'order_id': None,
            'place_at': place_at,
            'slices': slices,
            'status_message': (
                f'the order is recorded and its {slices} slices will be sent '
                f'from {place_at} until {WINDOW_ENDS_AT}'
            ),
            'skipped': [],
        }, 202

    def on_clock_tick(self, now):
        """Sends any slice whose time has come, marking the parent working once the first scheduled slice is out.

        Args:
            now (float): The Unix time of the tick.

        Returns:
            bool: True when a slice was sent on this tick.
        """
        acted = super().on_clock_tick(now)
        if acted and self.parent.state == 'received':
            state = 'working'
            if self.parent.legs[0].state == 'rejected':
                state = 'rejected'
            self.record_state(state, 'the closing price window has opened')
            self.save()
        return acted
