"""An order held back until a time of day."""

from unified_broker_interface.utilities.order_engine.base import SyntheticOrder
from unified_broker_interface.utilities.order_engine.utilities.moments import (
    Moments,
)


class Scheduled(SyntheticOrder):
    """An order placed at `at_time` rather than now.

    A nine-twenty short straddle, a three-ten entry. The caller says when, and the engine holds the order until then.

    Nothing is sent when the request arrives, so the answer the caller gets says the order is scheduled rather than placed, and carries the parent id they will need to find it later. That is the one place a synthetic type's answer differs in shape from an ordinary placement's, and it is unavoidable: there is no broker order to report because there is no broker order yet.

    The time is refused if it has already passed today. An order told to start at a time that has gone is far more likely to be a mistake than an instruction to wait until tomorrow, and holding a position overnight by inference is not a thing to do.
    """

    SYNTHETIC_TYPE = 'scheduled'
    WANTS_CLOCK = True

    def run(self, intent, started_at):
        """Records the order and waits, without sending anything.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when `at_time` is missing or has passed.
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

        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['place_at'] = at_time
        self.record_received()
        self.save()
        return {
            'broker': None,
            'instrument_id': self.parent.instrument_id,
            'parent_id': self.parent.parent_order_id,
            'tag': self.parent.tag,
            'outcome': 'scheduled',
            'order_id': None,
            'place_at': self.parent.parameters['at_time'],
            'status_message': (
                'the order is recorded and will be placed at '
                f'{self.parent.parameters["at_time"]}'
            ),
            'skipped': [],
        }, 202

    def on_clock_tick(self, now):
        """Places the order once its time has come.

        Args:
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the order was placed on this tick.
        """
        place_at = self.parent.parameters.get('place_at')
        if not isinstance(place_at, (int, float)) or now < place_at:
            return False
        if self.parent.legs:
            return False
        order = self.concrete_order(self.read_order(self.parent.body))
        body, _, _ = self.place_leg('entry', order, None)
        outcome = body.get('outcome')
        state = {
            'accepted': 'working',
            'rejected': 'rejected',
        }.get(outcome, 'failed')
        self.record_state(state, body.get('status_message'))
        self.save()
        return True
