"""Reads a `POST` body naming four instruments, one of them badly, and builds the answer list in request order.

The instrument routes accept a list of instruments in a JSON body. `InstrumentBatch` reads the body, turns every item into an `InstrumentQuery` or, when the item names no instrument properly, into the `RequestError` saying why, and keeps every other key as a parameter shared by the whole list. The route looks up only `valid_instruments()`, and `results()` then puts the answers back in the order of the request, with each bad item's own 400 entry in its place.

This program writes the body as a Python dictionary, as `request.get_json()` would return it, and uses JSON numbers and booleans where the query string would have had text. Instead of the instrument catalogue, a small stand-in answers each valid instrument: a found one with a short details dictionary and an unknown one with a 404 `RequestError`, as the catalogue does.

Notice that `"adjusted": false` was kept as the text `false` and that `"strike_price": 25000` was read as text and then parsed into the same `Decimal` a query string gives, that only three instruments were looked up, and that the answer list still has four entries with the bad one at index 2.

Run it from the project root:

    python examples/unified_broker_interface/utilities/instrument_batch/InstrumentBatch/example_1_answering_a_mixed_list.py
"""

import json

from unified_broker_interface.utilities.instrument_batch import (
    InstrumentBatch,
)
from unified_broker_interface.utilities.instrument_identity import (
    RequestError,
)


class StandInCatalogue:
    """A stand-in for the instrument catalogue that knows two instruments by name.

    Attributes:
        known (dict): Instrument ids by name.
    """

    def __init__(self):
        """Builds the catalogue.

        Returns:
            None: This method returns nothing.
        """
        self.known = {
            'INFY': '22222222-2222-5222-8222-000000000001',
            'NIFTY': '22222222-2222-5222-8222-000000000004',
        }

    def details_many(self, instruments):
        """Answers each instrument with a short details dictionary, or a 404 error when it is unknown.

        Args:
            instruments (list): The `InstrumentQuery` objects to answer.

        Returns:
            list: One details dict or `RequestError` per instrument, in order.
        """
        answers = []
        for instrument in instruments:
            instrument_id = self.known.get(instrument.name)
            if instrument_id is None:
                answers.append(RequestError(f'no instrument {instrument.segment} {instrument.name} is mapped on 2026-09-30', 404))
                continue
            answers.append({
                'instrument_id': instrument_id,
                'segment': instrument.segment,
            })
        return answers


class AnsweringAMixedListExample:
    """Reads a four-item body and prints the batch's parameters, queries and answer list.

    Attributes:
        body (dict): The decoded request body.
        catalogue (StandInCatalogue): The stand-in catalogue.
    """

    def __init__(self):
        """Builds the body and the stand-in catalogue.

        Returns:
            None: This method returns nothing.
        """
        self.body = {
            'date': '2026-09-30',
            'adjusted': False,
            'instruments': [
                {
                    'exchange': 'nse',
                    'segment': 'equities',
                    'symbol': 'INFY',
                },
                {
                    'exchange': 'nse',
                    'segment': 'equity_index_options',
                    'underlying_symbol': 'NIFTY',
                    'expiry_date': '2026-10-27',
                    'strike_price': 25000,
                    'option_type': 'CE',
                },
                {
                    'exchange': 'nse',
                    'segment': 'equities',
                },
                {
                    'exchange': 'nse',
                    'segment': 'equities',
                    'symbol': 'NOSUCHCO',
                },
            ],
        }
        self.catalogue = StandInCatalogue()

    def run(self):
        """Reads the body, answers the valid instruments and prints the answer list.

        Returns:
            None: This method returns nothing.
        """
        batch = InstrumentBatch(self.body)
        print(f'Shared parameters: {batch.parameters}')
        for index, instrument in enumerate(batch.instruments):
            if isinstance(instrument, RequestError):
                print(f'Item {index}: error {instrument.message}')
            else:
                print(f'Item {index}: {instrument.segment} {instrument.fields}')
        valid = batch.valid_instruments()
        print(f'Instruments looked up: {len(valid)}')
        answers = self.catalogue.details_many(valid)
        results = batch.results(answers)
        body = {
            'results': results,
        }
        print(json.dumps(body, indent=2))


if __name__ == '__main__':
    AnsweringAMixedListExample().run()
