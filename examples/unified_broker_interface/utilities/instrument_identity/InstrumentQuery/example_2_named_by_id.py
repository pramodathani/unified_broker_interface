"""Builds `InstrumentQuery` objects for instruments named by id, both by parsing a request and directly.

A request can name an instrument by its `instrument_id` instead of its identity fields. The query then holds only the id, written in the canonical lower-case UUID form, and has no exchange, segment, shape or fields, so its `name` is None. The catalogue reads such an instrument straight from the identity hash without searching.

The program parses an id given in upper case with spaces around it, and then builds two queries directly, as a caller that already knows what it wants would: one by id and one by identity fields. Building a query checks nothing, so a caller that builds one directly must pass the fields already in the parsed form. Nothing touches a data store.

Notice that the parsed id has been lower-cased and stripped, and that a query built without fields holds an empty dictionary, not None.

Run it from the project root:

    python examples/unified_broker_interface/utilities/instrument_identity/InstrumentQuery/example_2_named_by_id.py
"""

from unified_broker_interface.utilities import instrument_identity
from unified_broker_interface.utilities.instrument_identity import (
    InstrumentQuery,
)


class NamedByIdExample:
    """Parses and builds queries and prints what each holds."""

    def describe(self, label, query):
        """Prints one query's attributes and name.

        Args:
            label (str): What the query is, for the printout.
            query (InstrumentQuery): The query.

        Returns:
            None: This method returns nothing.
        """
        print(f'{label}:')
        print(f'  instrument_id {query.instrument_id}')
        print(f'  exchange {query.exchange}, segment {query.segment}, shape {query.shape}')
        print(f'  fields {query.fields}, name {query.name}')

    def run(self):
        """Parses one id, then builds a query by id and one by identity.

        Returns:
            None: This method returns nothing.
        """
        parsed = instrument_identity.parse_instrument({
            'instrument_id': ' 22222222-2222-5222-8222-00000000000A ',
        })
        self.describe('Parsed from a request', parsed)
        by_id = InstrumentQuery(instrument_id='22222222-2222-5222-8222-000000000001')
        self.describe('Built by id', by_id)
        by_identity = InstrumentQuery(
            exchange='bse',
            segment='bse_equities',
            shape='security',
            fields={
                'symbol': 'RELIANCE',
            },
        )
        self.describe('Built by identity', by_identity)


if __name__ == '__main__':
    NamedByIdExample().run()
