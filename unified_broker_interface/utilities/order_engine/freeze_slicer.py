"""An order too large for one exchange order, sent as several that each fit."""

import math

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import (
    OUTCOME_PARENT_STATES,
    SyntheticOrder,
)


class FreezeSlicer(SyntheticOrder):
    """Splits an order above the exchange's freeze limit into orders that are each below it.

    An exchange rejects any single derivative order larger than its freeze quantity outright. Somebody wanting to trade more than that has to send several orders, and doing it by hand means doing arithmetic in lots at the moment they least want to.

    Every slice goes to the **same** broker, chosen once. Spreading them would look cheaper, and would mean the position ends up split across brokers, where closing it needs one order per broker and the freeze limit has to be worked out again for each.

    The freeze quantity is read from the broker the order is going to, and compared against the quantity in that broker's own terms. That is not fussiness: for one MCX silver option, brokers whose lot size is 30 report a freeze quantity of 600 and brokers whose lot size is 1 report 20, and both mean twenty lots. Comparing one broker's figure against another broker's quantity would be wrong by a factor of thirty.

    Only five of the ten brokers publish a freeze quantity at all. When the chosen broker does not, the order is sent whole and the event log records that no limit was known. An exchange rejection is then visible and recoverable; guessing a limit from another broker would be neither.
    """

    SYNTHETIC_TYPE = 'freeze_slicer'
    MOST_SLICES = 20

    def run(self, intent, started_at):
        """Places the order as one or several, each below the freeze limit.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For an order answered without calling a broker.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        prepared = self.placement.prepare(order, self.parent.instrument_id)
        if order.dry_run:
            return self.placement.dry_run_answer(prepared, started_at)

        broker_name = prepared.broker_name
        freeze_quantity = self.freeze_quantity(broker_name)
        slices = self.slices(
            order,
            prepared.broker_quantity,
            freeze_quantity,
        )

        self.record_received()
        self.save()

        answers = []
        for slice_order in slices:
            body, status, _ = self.place_leg(
                'slice',
                slice_order,
                started_at,
                broker_name,
            )
            answers.append((body, status))
        self.finish(answers)
        return self.answer(answers, broker_name, freeze_quantity, len(slices))

    def freeze_quantity(self, broker_name):
        """The freeze quantity the chosen broker publishes, in that broker's own terms.

        Args:
            broker_name (str): The broker the order is going to.

        Returns:
            int | None: The freeze quantity, or None when that broker publishes none.
        """
        attributes = self.placement.broker_attributes(
            self.parent.instrument_id,
        )
        published = (attributes.get(broker_name) or {}).get('freeze_quantity')
        if published is None:
            return None
        try:
            freeze_quantity = int(float(published))
        except (TypeError, ValueError):
            return None
        if freeze_quantity < 1:
            return None
        return freeze_quantity

    def slices(self, order, broker_quantity, freeze_quantity):
        """The orders to send, in units, each small enough for the exchange to take.

        The split is even rather than filling each slice to the limit and leaving a remainder, because a run of full-sized orders followed by a small one is a recognisable pattern, and because an even split keeps every slice the same distance from the limit if the limit changes intraday.

        Args:
            order (PlaceOrderRequest): The validated order, whose quantity is in units.
            broker_quantity (int | None): The same quantity in the broker's own terms.
            freeze_quantity (int | None): The broker's freeze quantity, in the same terms.

        Returns:
            list: One `PlaceOrderRequest` per slice, quantities in units.

        Raises:
            RefusedRequestError: With HTTP 400 when the order would need more slices than the engine will send at once.
        """
        if (
            freeze_quantity is None
            or not broker_quantity
            or broker_quantity <= freeze_quantity
        ):
            return [
                order,
            ]
        wanted = math.ceil(broker_quantity / freeze_quantity)
        if wanted > self.MOST_SLICES:
            raise RefusedRequestError.refusal(
                f'this order is {wanted} times the freeze limit, which would '
                f'take {wanted} orders; the engine sends at most '
                f'{self.MOST_SLICES} at once',
                400,
                instrument_id=self.parent.instrument_id,
            )
        return self.even_split(order, wanted)

    def even_split(self, order, wanted):
        """Splits the order's quantity into `wanted` orders as evenly as the lot size allows.

        Args:
            order (PlaceOrderRequest): The validated order.
            wanted (int): How many slices to make.

        Returns:
            list: One `PlaceOrderRequest` per slice.
        """
        quantity = order.quantity
        each = quantity // wanted
        remainder = quantity - each * wanted
        slices = []
        for index in range(wanted):
            slice_quantity = each + (1 if index < remainder else 0)
            if slice_quantity < 1:
                continue
            slices.append(
                order.with_quantities(slice_quantity, 0),
            )
        return slices

    def finish(self, answers):
        """Records the parent's state from what the slices did.

        A parent is `working` when any slice was accepted, because there is something live at a broker whatever happened to the rest. It is `failed` when any slice's outcome is unknown, because then nobody knows what is live.

        Args:
            answers (list): One `(body, status)` per slice.

        Returns:
            None: This method returns nothing.
        """
        outcomes = [body.get('outcome') for body, _ in answers]
        if 'unknown' in outcomes:
            state = 'failed'
        elif 'accepted' in outcomes:
            state = 'working'
        else:
            state = OUTCOME_PARENT_STATES.get(
                outcomes[0] if outcomes else None,
                'failed',
            )
        self.record_state(state, self.first_message(answers))
        self.save()

    def first_message(self, answers):
        """The first status message any slice came back with, for a person reading the parent.

        Args:
            answers (list): One `(body, status)` per slice.

        Returns:
            str | None: The message.
        """
        for body, _ in answers:
            if body.get('status_message'):
                return body['status_message']
        return None

    def answer(self, answers, broker_name, freeze_quantity, sent):
        """The one answer the waiting API worker gets for a sliced order.

        Args:
            answers (list): One `(body, status)` per slice.
            broker_name (str): The broker every slice went to.
            freeze_quantity (int | None): The freeze limit used, or None when the broker published none.
            sent (int): How many slices were sent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int), which is the worst any slice returned.
        """
        bodies = [body for body, _ in answers]
        statuses = [status for _, status in answers]
        return {
            'broker': broker_name,
            'instrument_id': self.parent.instrument_id,
            'parent_id': self.parent.parent_order_id,
            'tag': self.parent.tag,
            'outcome': self.worst_outcome(bodies),
            'order_ids': [body.get('order_id') for body in bodies],
            'slices': sent,
            'freeze_quantity': freeze_quantity,
            'status_message': self.first_message(answers),
            'skipped': bodies[0].get('skipped') if bodies else [],
            'timing_ms': bodies[0].get('timing_ms') if bodies else {},
        }, max(statuses) if statuses else 200

    def worst_outcome(self, bodies):
        """The outcome a caller should act on when several orders had several outcomes.

        Args:
            bodies (list): Each slice's answer body.

        Returns:
            str: `unknown` if any slice is unknown, then `rejected` if any was refused, else `accepted`.
        """
        outcomes = [body.get('outcome') for body in bodies]
        if 'unknown' in outcomes:
            return 'unknown'
        if 'rejected' in outcomes:
            return 'rejected'
        return 'accepted'
