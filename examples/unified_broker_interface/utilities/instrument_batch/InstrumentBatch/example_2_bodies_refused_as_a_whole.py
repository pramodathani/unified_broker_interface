"""Shows which request bodies `InstrumentBatch` refuses outright, and how it reads single JSON values and builds single answer entries.

A body is refused as a whole, with a `RequestError` the route answers with 400, when it is not a JSON object, when its `instruments` list is missing or empty, or when a shared parameter is an object or a list. Items that are not objects are not refused as a whole; they get their own error entry, as any badly named item does.

The program tries five bodies, then uses one accepted batch to show its two building blocks directly: `as_text`, which spells a JSON value the way the query string would, and `parse_item` and `entry`, which read one item and build one entry of the answer list. It uses no data store.

Notice that None, which is what Flask gives for a body that is not JSON, is refused with the same message as a JSON list, and that an item that is a plain string becomes its own 400 entry rather than refusing the whole body.

Run it from the project root:

    python examples/unified_broker_interface/utilities/instrument_batch/InstrumentBatch/example_2_bodies_refused_as_a_whole.py
"""

from unified_broker_interface.utilities.instrument_batch import (
    InstrumentBatch,
)
from unified_broker_interface.utilities.instrument_identity import (
    RequestError,
)


class BodiesRefusedAsAWholeExample:
    """Tries bodies that are refused, then reads values and items with an accepted batch.

    Attributes:
        bodies (list): Pairs of a label and a decoded body.
    """

    def __init__(self):
        """Builds the bodies to try.

        Returns:
            None: This method returns nothing.
        """
        self.bodies = [
            (
                'Not JSON at all',
                None,
            ),
            (
                'A JSON list',
                [
                    'INFY',
                ],
            ),
            (
                'An empty instruments list',
                {
                    'instruments': [],
                },
            ),
            (
                'A shared parameter that is a list',
                {
                    'date': [
                        '2026-09-29',
                        '2026-09-30',
                    ],
                    'instruments': [
                        {
                            'instrument_id': '22222222-2222-5222-8222-000000000001',
                        },
                    ],
                },
            ),
            (
                'An item that is a string',
                {
                    'instruments': [
                        'INFY',
                    ],
                },
            ),
        ]

    def run(self):
        """Tries each body, then reads values and one item through an accepted batch.

        Returns:
            None: This method returns nothing.
        """
        batch = None
        for label, body in self.bodies:
            try:
                batch = InstrumentBatch(body)
            except RequestError as error:
                print(f'{label}: refused with {error.status}: {error.message}')
                continue
            print(f'{label}: accepted, answer entries {batch.results([])}')
        values = [
            None,
            True,
            7,
            2.5,
            'day',
        ]
        for value in values:
            print(f'as_text({value!r}) = {batch.as_text("interval", value)!r}')
        item_body = {
            'instrument_id': '22222222-2222-5222-8222-000000000001',
        }
        item = batch.parse_item(item_body)
        print(f'parse_item found instrument_id {item.instrument_id}')
        answer = {
            'last_price': 1521.4,
        }
        print(f'entry for an answer: {batch.entry(0, answer)}')
        print(f'entry for an error: {batch.entry(1, RequestError("no instrument", 404))}')


if __name__ == '__main__':
    BodiesRefusedAsAWholeExample().run()
