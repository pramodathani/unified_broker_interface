"""Turns a misleading "not mapped" refusal into an honest one when yesterday's catalogue has expired.

The catalogue keys for a mapping date expire at midnight, but `unified:catalogue:current_date` keeps naming that date until the morning's mapping publishes a new one. In that gap every instrument looks unmapped. `CatalogueAvailability.explained` runs only after an order was already refused as not mapped: it checks whether the catalogue itself is there, and if not, replaces the 404 with a 503 that says so.

A small stand-in replaces the Redis client. It answers `get` and `exists` from a dictionary and records each command, so the output shows exactly which two keys the check reads. The program asks twice: once with the catalogue gone, once with it present.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/catalogue_availability/CatalogueAvailability/example_1_catalogue_expired.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.catalogue_availability import (
    CatalogueAvailability,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)


class DictionaryRedis:
    """A stand-in for the Redis client that answers from a dictionary and records every command.

    Attributes:
        values (dict): The keys and their string values.
        commands (list): The commands received, as text.
    """

    def __init__(self, values):
        """Builds the stand-in.

        Args:
            values (dict): The keys and their string values.

        Returns:
            None: This method returns nothing.
        """
        self.values = values
        self.commands = []

    def get(self, key):
        """Returns a key's value.

        Args:
            key (str): The key.

        Returns:
            str | None: The value, or None when the key is absent.
        """
        self.commands.append(f'GET {key}')
        return self.values.get(key)

    def exists(self, key):
        """Counts whether a key exists.

        Args:
            key (str): The key.

        Returns:
            int: 1 when the key exists, otherwise 0.
        """
        self.commands.append(f'EXISTS {key}')
        if key in self.values:
            return 1
        return 0


class CatalogueExpiredExample:
    """Explains the same "not mapped" refusal with and without the catalogue in Redis.

    Attributes:
        refusal (RefusedRequestError): The refusal the order was first answered with.
    """

    def __init__(self):
        """Builds the original refusal.

        Returns:
            None: This method returns nothing.
        """
        self.refusal = RefusedRequestError.refusal('the instrument is not mapped', 404)

    def explain(self, label, values):
        """Explains the refusal against one state of Redis and prints the result.

        Args:
            label (str): What the state of Redis is.
            values (dict): The keys and values the stand-in holds.

        Returns:
            None: This method returns nothing.
        """
        cache = DictionaryRedis(values)
        availability = CatalogueAvailability(cache)
        answer = availability.explained(self.refusal)
        print(f'{label}:')
        print(f'  commands: {cache.commands}')
        print(f'  HTTP {answer.status}: {answer.body["error"]}')

    def run(self):
        """Explains the refusal with the catalogue missing and with it present.

        Returns:
            None: This method returns nothing.
        """
        self.explain(
            'Catalogue expired',
            {
                'unified:catalogue:current_date': '2026-09-29',
            },
        )
        self.explain(
            'Catalogue present',
            {
                'unified:catalogue:current_date': '2026-09-30',
                'unified:catalogue:2026-09-30:identity': 'present',
            },
        )


if __name__ == '__main__':
    CatalogueExpiredExample().run()
