"""Shows that an export with two documents for the same exchange raises `DetailsImportError` and writes nothing.

`import_details` loads three Compass exports from a folder into the `exchange_details`, `broker_details` and `user_details` collections. It reads and checks all three before writing any, and it refuses an export in which two exchanges share a code or two brokers share a broker name. The error is a `DetailsImportError`, which the `import-api-details` command prints before stopping.

This program writes three tiny exports into a temporary folder. The exchange export lists NSE twice, once as `NSE` and once as ` nse `, which both become the code `nse`. The broker and user exports are well formed and hold no real details. A stand-in MongoDB database records every collection it hands out and every write, so the program can show that nothing was written. Only the error message is printed, never the temporary folder's path.

Notice that the error names the collection, the key and the duplicated value, and that the stand-in database received no write.

Run it from the project root:

    python examples/unified_broker_interface/utilities/import_details/DetailsImportError/example_2_duplicate_exchange_in_export.py
"""

import json
import pathlib
import tempfile

from unified_broker_interface.utilities import import_details
from unified_broker_interface.utilities.import_details import (
    DetailsImportError,
)


class RecordingCollection:
    """A stand-in MongoDB collection that records every write it is asked for.

    Attributes:
        name (str): The collection's name.
        writes (list): The names of the write methods called, shared with the database.
    """

    def __init__(self, name, writes):
        """Builds the collection.

        Args:
            name (str): The collection's name.
            writes (list): The list every write is recorded in.

        Returns:
            None: This method returns nothing.
        """
        self.name = name
        self.writes = writes

    def create_index(self, key, unique):
        """Records an index creation.

        Args:
            key (str): The indexed field.
            unique (bool): Whether the index is unique.

        Returns:
            None: This method returns nothing.
        """
        del unique
        self.writes.append(f'{self.name}.create_index({key})')

    def update_one(self, query, update, upsert):
        """Records an upsert.

        Args:
            query (dict): The filter.
            update (dict): The update.
            upsert (bool): Whether to insert when nothing matches.

        Returns:
            None: This method returns nothing.
        """
        del update
        del upsert
        self.writes.append(f'{self.name}.update_one({query})')


class RecordingDatabase:
    """A stand-in MongoDB database that hands out recording collections.

    Attributes:
        writes (list): Every write asked of any collection.
    """

    def __init__(self):
        """Builds the database with no writes recorded.

        Returns:
            None: This method returns nothing.
        """
        self.writes = []

    def __getitem__(self, collection_name):
        """Hands out a collection by name.

        Args:
            collection_name (str): The collection's name.

        Returns:
            RecordingCollection: The collection.
        """
        return RecordingCollection(collection_name, self.writes)


class DuplicateExchangeInExportExample:
    """Imports a folder of exports that lists NSE twice.

    Attributes:
        exports (dict): The documents of each export, by file name relative to the folder.
    """

    def __init__(self):
        """Builds the three exports' documents.

        Returns:
            None: This method returns nothing.
        """
        self.exports = {
            import_details.EXCHANGES_FILE: [
                {
                    'name': 'National Stock Exchange of India',
                    'short_name': 'NSE',
                },
                {
                    'name': 'National Stock Exchange',
                    'short_name': ' nse ',
                },
            ],
            str(import_details.BROKERS_FILE): [
                {
                    'borker_name': 'Zerodha',
                },
            ],
            import_details.USER_DETAILS_FILE: [
                {
                    'name': 'Example User',
                },
            ],
        }

    def write_exports(self, directory):
        """Writes each export as a JSON file under the folder.

        Args:
            directory (str): The folder.

        Returns:
            None: This method returns nothing.
        """
        for file_name, documents in self.exports.items():
            path = pathlib.Path(directory, file_name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(documents))

    def run(self):
        """Writes the exports, imports them and prints the error and the writes made.

        Returns:
            None: This method returns nothing.
        """
        database = RecordingDatabase()
        with tempfile.TemporaryDirectory() as directory:
            self.write_exports(directory)
            try:
                import_details.import_details(database, directory)
            except DetailsImportError as error:
                print(f'{type(error).__name__}: {error}')
        print(f'Writes made: {database.writes}')


if __name__ == '__main__':
    DuplicateExchangeInExportExample().run()
