"""Parses a stock, a future and an option from query strings into `InstrumentQuery` objects and reads what each holds.

An instrument endpoint accepts an instrument by its identity: an exchange, a segment, and the fields that segment's shape needs. A security needs a `symbol`, a future an `underlying_symbol` and an `expiry_date`, and an option those two plus a `strike_price` and an `option_type`. `parse_instrument` checks them and answers an `InstrumentQuery`, whose `name` is the symbol or underlying the catalogue lists it under.

This program parses three query strings, written as plain dictionaries the way Flask's `request.args` hands them over. It needs no data store, because a query only records what the request asked for; the catalogue turns it into an instrument id later.

Notice that the bare segment names are given the exchange prefix, that names and option types are upper-cased, that the expiry becomes a date and the strike a `Decimal`, and that `name` is the symbol for the stock and the underlying for the derivatives.

Run it from the project root:

    python examples/unified_broker_interface/utilities/instrument_identity/InstrumentQuery/example_1_three_shapes_of_instrument.py
"""

from unified_broker_interface.utilities import instrument_identity


class ThreeShapesOfInstrumentExample:
    """Parses one query string of each shape and prints the query.

    Attributes:
        query_strings (list): The query parameters of each request.
    """

    def __init__(self):
        """Builds the three query strings.

        Returns:
            None: This method returns nothing.
        """
        self.query_strings = [
            {
                'exchange': 'NSE',
                'segment': 'equities',
                'symbol': 'infy',
            },
            {
                'exchange': 'nse',
                'segment': 'nse_equity_index_futures',
                'underlying_symbol': 'nifty',
                'expiry_date': '2026-10-27',
            },
            {
                'exchange': 'nse',
                'segment': 'equity_index_options',
                'underlying_symbol': 'NIFTY',
                'expiry_date': '2026-10-27',
                'strike_price': '25000',
                'option_type': 'ce',
            },
        ]

    def run(self):
        """Parses each query string and prints every attribute of the query.

        Returns:
            None: This method returns nothing.
        """
        for query_string in self.query_strings:
            query = instrument_identity.parse_instrument(query_string)
            print(f'{query.shape} named {query.name}')
            print(f'  exchange {query.exchange}, segment {query.segment}, instrument_id {query.instrument_id}')
            print(f'  fields {query.fields}')


if __name__ == '__main__':
    ThreeShapesOfInstrumentExample().run()
