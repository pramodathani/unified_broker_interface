"""An entry that cannot be placed without the stop that protects it."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.bracket import Bracket


class Cover(Bracket):
    """A bracket with no target: an entry and a compulsory stop, and nothing else.

    Brokers sold this as a product — Flattrade calls it a cover order — and gave higher leverage on it, because an order that cannot exist without a stop is an order whose worst case the broker knows. The product is restricted through Flattrade's API, which is why it is built here.

    The difference from a bracket is one line of validation and it is the whole point of the type. A bracket will take a stop, a target, or both. A cover order **requires** the stop and **refuses** a target. Somebody who wants a target is asking for a bracket and should say so; letting the two shade into each other would mean a cover order that silently has no stop, which is the one thing it is for.

    Everything else it inherits: the stop is armed on the first partial fill rather than after the entry completes, it follows the entry up as more fills arrive, and it is cancelled if the entry is cancelled with nothing filled.
    """

    SYNTHETIC_TYPE = 'cover'

    def run(self, intent, started_at):
        """Checks that there is a stop and no target, then runs as a bracket does.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when there is no stop price or there is a target price.
        """
        parameters = self.parent.parameters
        if parameters.get('stop_price') is None:
            raise RefusedRequestError.refusal(
                'a cover order is an entry and a compulsory stop, so it needs '
                'stop_price; without one it is a plain order',
                400,
            )
        if parameters.get('target_price') is not None:
            raise RefusedRequestError.refusal(
                'a cover order has no target; an entry with both a stop and a '
                'target is a bracket, so ask for one of those instead',
                400,
            )
        return super().run(intent, started_at)
