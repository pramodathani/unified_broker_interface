"""Shows the refusals `CatalogueAvailability.explained` passes through unchanged.

The check only ever rewrites a 404 whose message is "the instrument is not mapped". Any other refusal is returned as it came, without touching Redis. A "not mapped" refusal is also returned unchanged when Redis names no mapping date, and when Redis cannot be read at all, because the check must never turn a clear answer into a failure of its own.

A stand-in replaces the Redis client. It can be told to raise `redis.ConnectionError` on every command, and it records the commands it receives, so the output shows that the first refusal cost no Redis command at all.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/catalogue_availability/CatalogueAvailability/example_2_refusals_left_alone.py
"""

import redis

from unified_broker_interface.utilities.broker_orders.utilities.catalogue_availability import (
    CatalogueAvailability,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)


class StandInRedis:
    """A stand-in for the Redis client that holds no keys and may fail every command.

    Attributes:
        failing (bool): Whether every command raises a connection error.
        commands (list): The commands received, as text.
    """

    def __init__(self, failing):
        """Builds the stand-in.

        Args:
            failing (bool): Whether every command raises a connection error.

        Returns:
            None: This method returns nothing.
        """
        self.failing = failing
        self.commands = []

    def get(self, key):
        """Returns nothing, or fails.

        Args:
            key (str): The key.

        Returns:
            None: No key is held.

        Raises:
            redis.ConnectionError: When the stand-in is failing.
        """
        self.commands.append(f'GET {key}')
        if self.failing:
            raise redis.ConnectionError('stand-in failure')
        return None

    def exists(self, key):
        """Reports that no key exists.

        Args:
            key (str): The key.

        Returns:
            int: Always 0.
        """
        self.commands.append(f'EXISTS {key}')
        return 0


class RefusalsLeftAloneExample:
    """Explains three refusals that come back unchanged."""

    def show(self, label, refusal, cache):
        """Explains one refusal and prints the result.

        Args:
            label (str): What the case is.
            refusal (RefusedRequestError): The refusal to explain.
            cache (StandInRedis): The Redis stand-in.

        Returns:
            None: This method returns nothing.
        """
        availability = CatalogueAvailability(cache)
        answer = availability.explained(refusal)
        unchanged = answer is refusal
        print(f'{label}: HTTP {answer.status}, unchanged={unchanged}, commands={cache.commands}')

    def run(self):
        """Explains a different refusal, a refusal with no mapping date and one with Redis failing.

        Returns:
            None: This method returns nothing.
        """
        not_mapped = RefusedRequestError.refusal('the instrument is not mapped', 404)
        other = RefusedRequestError.refusal('no broker can take the order', 503)
        self.show('Another refusal', other, StandInRedis(False))
        self.show('No mapping date', not_mapped, StandInRedis(False))
        self.show('Redis failing', not_mapped, StandInRedis(True))


if __name__ == '__main__':
    RefusalsLeftAloneExample().run()
