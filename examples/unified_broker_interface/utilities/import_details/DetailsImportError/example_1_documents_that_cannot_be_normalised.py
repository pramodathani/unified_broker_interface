"""Normalises exchange and broker documents from the detail exports, and catches the `DetailsImportError` raised by ones that cannot be loaded.

The REST API's exchange and broker profiles come from MongoDB Compass exports. Before loading them, `import_details` gives every exchange document an `exchange` code taken from its `short_name`, and turns every broker document's display name into this project's broker code. A document that cannot be turned into one of those raises `DetailsImportError`, and because every document is normalised before anything is written, one bad document stops the whole import.

This program builds the documents in memory, so it reads no export and touches no database. It normalises one good document of each kind, then three bad ones: an exchange with no `short_name`, a broker whose display name is not in the list of known names, and a broker display name mapped to a code the project does not support.

Notice that the good broker document keeps the old export's misspelt `borker_name` field out of the result, and that each error message quotes the value that could not be used.

Run it from the project root:

    python examples/unified_broker_interface/utilities/import_details/DetailsImportError/example_1_documents_that_cannot_be_normalised.py
"""

from unified_broker_interface.utilities import import_details
from unified_broker_interface.utilities.import_details import (
    DetailsImportError,
)


class DocumentsThatCannotBeNormalisedExample:
    """Normalises good and bad documents and prints the result or the error."""

    def normalise(self, label, normaliser, document):
        """Normalises one document and prints the result or the error.

        Args:
            label (str): What the document is, for the printout.
            normaliser (callable): `normalise_exchange` or `normalise_broker`.
            document (dict): The exported document.

        Returns:
            None: This method returns nothing.
        """
        try:
            normalised = normaliser(document)
        except DetailsImportError as error:
            print(f'{label}: {type(error).__name__}: {error}')
            return
        print(f'{label}: {normalised}')

    def run(self):
        """Normalises two good documents and three bad ones.

        Returns:
            None: This method returns nothing.
        """
        self.normalise('Good exchange', import_details.normalise_exchange, {
            'name': 'National Stock Exchange of India',
            'short_name': ' NSE ',
        })
        self.normalise('Good broker', import_details.normalise_broker, {
            'borker_name': 'Zerodha',
            'website': 'https://zerodha.com',
        })
        self.normalise('Exchange without short name', import_details.normalise_exchange, {
            'name': 'Metropolitan Stock Exchange',
        })
        self.normalise('Unknown broker', import_details.normalise_broker, {
            'broker_name': 'Upstox',
        })
        import_details.BROKER_CODES['Angel One'] = 'angel_one'
        self.normalise('Unsupported broker code', import_details.normalise_broker, {
            'broker_name': 'Angel One',
        })


if __name__ == '__main__':
    DocumentsThatCannotBeNormalisedExample().run()
