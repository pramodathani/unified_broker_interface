"""Raises `RequestError` with a status other than 400 and turns it into the JSON answer an endpoint sends.

A `RequestError` carries the HTTP status to answer with as well as the message. The parsers use 400, but the instrument catalogue raises it with 404 when an instrument is not mapped and 503 when nothing has been mapped yet or the cache is unreachable. The instruments blueprint catches it in one place and answers `{"error": ...}` with that status.

This program writes a tiny lookup that raises `RequestError` the same way the catalogue does, and a small answering class that does what the blueprint's handler does. It uses a dictionary of two known instruments instead of the real catalogue, so it needs no Redis or database.

Notice that the status defaults to 400 when none is given, that the error's text is its message, and that the three answers carry three different statuses.

Run it from the project root:

    python examples/unified_broker_interface/utilities/instrument_identity/RequestError/example_2_answering_with_the_status.py
"""

import json

from unified_broker_interface.utilities.instrument_identity import (
    RequestError,
)


class StandInCatalogue:
    """A stand-in catalogue that knows two instruments and raises `RequestError` as the real one does.

    Attributes:
        mapped (bool): Whether anything has been mapped yet.
        known (dict): Instrument ids by symbol.
    """

    def __init__(self, mapped):
        """Builds the catalogue.

        Args:
            mapped (bool): Whether anything has been mapped yet.

        Returns:
            None: This method returns nothing.
        """
        self.mapped = mapped
        self.known = {
            'INFY': '22222222-2222-5222-8222-000000000001',
            'RELIANCE': '22222222-2222-5222-8222-000000000002',
        }

    def resolve(self, symbol):
        """Finds a symbol's instrument id.

        Args:
            symbol (str): The symbol asked for.

        Returns:
            str: The instrument id.

        Raises:
            RequestError: With 400 for an empty symbol, 503 when nothing is mapped, and 404 for an unknown symbol.
        """
        if not symbol:
            raise RequestError('symbol is required')
        if not self.mapped:
            raise RequestError('no instruments have been mapped yet', 503)
        if symbol not in self.known:
            raise RequestError(f'no instrument nse_equities {symbol} is mapped on 2026-09-30', 404)
        return self.known[symbol]


class AnsweringWithTheStatusExample:
    """Looks up three symbols and prints the answer an endpoint would send for each."""

    def answer(self, catalogue, symbol):
        """Builds the status and JSON body an endpoint would send for one lookup.

        Args:
            catalogue (StandInCatalogue): The catalogue to look in.
            symbol (str): The symbol asked for.

        Returns:
            tuple: A pair of the HTTP status (int) and the JSON body (str).
        """
        try:
            instrument_id = catalogue.resolve(symbol)
        except RequestError as error:
            body = {
                'error': error.message,
            }
            return error.status, json.dumps(body)
        body = {
            'instrument_id': instrument_id,
        }
        return 200, json.dumps(body)

    def run(self):
        """Prints the answer for a known symbol, an unknown one, an empty one and an unmapped catalogue.

        Returns:
            None: This method returns nothing.
        """
        error = RequestError('interval must be one of minute, day')
        print(f'Default status: {error.status}; text: {error}')
        mapped = StandInCatalogue(True)
        lookups = [
            (
                mapped,
                'INFY',
            ),
            (
                mapped,
                'TCS',
            ),
            (
                mapped,
                '',
            ),
            (
                StandInCatalogue(False),
                'INFY',
            ),
        ]
        for catalogue, symbol in lookups:
            status, body = self.answer(catalogue, symbol)
            print(f'{symbol!r}: {status} {body}')


if __name__ == '__main__':
    AnsweringWithTheStatusExample().run()
