"""Catches the `RequestError` raised by query parameters the instrument endpoints cannot use, and reads its message and HTTP status.

Every instrument endpoint reads its query string through the parsers in `instrument_identity`. When a parameter cannot be used, the parser raises `RequestError`, and the blueprint answers with the error's `status` and a body carrying its `message`. The parsers always use status 400, because the fault is in the request.

This program feeds the parsers five bad query strings, written as plain dictionaries, the way Flask's `request.args` would hand them over. Nothing is looked up, so no data store is needed.

Notice that each message says exactly which parameter was wrong and what it should look like, and that the status is 400 every time.

Run it from the project root:

    python examples/unified_broker_interface/utilities/instrument_identity/RequestError/example_1_bad_query_parameters.py
"""

from unified_broker_interface.utilities import instrument_identity
from unified_broker_interface.utilities.instrument_identity import (
    RequestError,
)


class BadQueryParametersExample:
    """Parses five bad query strings and prints each error's status and message.

    Attributes:
        bad_queries (list): Pairs of a label and the query parameters.
    """

    def __init__(self):
        """Builds the bad query strings.

        Returns:
            None: This method returns nothing.
        """
        self.bad_queries = [
            (
                'Nothing named',
                {},
            ),
            (
                'Instrument id that is not a UUID',
                {
                    'instrument_id': '12345',
                },
            ),
            (
                'Unknown exchange',
                {
                    'exchange': 'lse',
                    'segment': 'equities',
                    'symbol': 'VOD',
                },
            ),
            (
                'Option without a strike',
                {
                    'exchange': 'nse',
                    'segment': 'equity_index_options',
                    'underlying_symbol': 'NIFTY',
                    'expiry_date': '2026-10-27',
                    'option_type': 'CE',
                },
            ),
            (
                'Option type that is not CE or PE',
                {
                    'exchange': 'nse',
                    'segment': 'equity_index_options',
                    'underlying_symbol': 'NIFTY',
                    'expiry_date': '2026-10-27',
                    'strike_price': '25000',
                    'option_type': 'CALL',
                },
            ),
        ]

    def run(self):
        """Parses each query and prints the error.

        Returns:
            None: This method returns nothing.
        """
        for label, query in self.bad_queries:
            try:
                instrument_identity.parse_instrument(query)
            except RequestError as error:
                print(f'{label}: {error.status} {error.message}')
        try:
            instrument_identity.parse_int('500', 'limit', 50, 1, 200)
        except RequestError as error:
            print(f'Limit out of range: {error.status} {error.message}')


if __name__ == '__main__':
    BadQueryParametersExample().run()
