"""Copies the real calendar files into a stand-in MongoDB, then shows the `CalendarCopyError` raised when an exchange has no document to copy into.

`copy_exchange_calendars` writes each exchange's trading hours, holidays and special sessions into that exchange's document in `exchange_details`. It only adds fields to documents the detail import created, so it first checks that every exchange in `TRADING_HOURS` has one. If any is missing it raises `CalendarCopyError` before writing anything, and the message says to import the exports first.

The program reads the project's own calendar files, and stands in for the MongoDB database with a small class that holds exchange documents in a list and records every update. The first copy runs against a database holding all four exchanges and prints the report. The second runs against one holding only NSE and BSE.

Notice that the first copy updates four documents and that the second copy updates none, because the check comes before the first write.

Run it from the project root:

    python examples/unified_broker_interface/utilities/exchange_calendar/CalendarCopyError/example_2_exchange_document_missing.py
"""

from unified_broker_interface.utilities import exchange_calendar
from unified_broker_interface.utilities.exchange_calendar import (
    CalendarCopyError,
)


class StandInCollection:
    """A stand-in MongoDB collection holding exchange documents and recording updates.

    Attributes:
        documents (list): The documents held.
        updates (list): The exchange code of every document updated.
    """

    def __init__(self, exchange_codes):
        """Builds a collection with one bare document per exchange.

        Args:
            exchange_codes (list): The exchanges that have a document.

        Returns:
            None: This method returns nothing.
        """
        self.documents = []
        for exchange_code in exchange_codes:
            self.documents.append({
                'exchange': exchange_code,
            })
        self.updates = []

    def find(self, query, projection):
        """Answers every document, as a query with an empty filter does.

        Args:
            query (dict): The filter, which is always empty here.
            projection (dict): The fields to return, which this stand-in ignores.

        Returns:
            list: The documents.
        """
        del query
        del projection
        return list(self.documents)

    def update_one(self, query, update):
        """Records an update of one document.

        Args:
            query (dict): The filter naming the exchange.
            update (dict): The update, which this stand-in does not apply.

        Returns:
            None: This method returns nothing.
        """
        del update
        self.updates.append(query['exchange'])


class StandInDatabase:
    """A stand-in MongoDB database with one `exchange_details` collection.

    Attributes:
        exchange_details (StandInCollection): The collection.
    """

    def __init__(self, exchange_codes):
        """Builds the database.

        Args:
            exchange_codes (list): The exchanges that have a document.

        Returns:
            None: This method returns nothing.
        """
        self.exchange_details = StandInCollection(exchange_codes)

    def __getitem__(self, collection_name):
        """Hands out a collection by name.

        Args:
            collection_name (str): The collection's name.

        Returns:
            StandInCollection: The collection.

        Raises:
            KeyError: When the collection is not `exchange_details`.
        """
        if collection_name != 'exchange_details':
            raise KeyError(collection_name)
        return self.exchange_details


class ExchangeDocumentMissingExample:
    """Copies the calendars into a complete database and into one missing two exchanges."""

    def copy(self, exchange_codes):
        """Copies the calendars into a database holding the given exchanges and prints the outcome.

        Args:
            exchange_codes (list): The exchanges that have a document.

        Returns:
            None: This method returns nothing.
        """
        database = StandInDatabase(exchange_codes)
        print(f'Exchanges with a document: {exchange_codes}')
        try:
            report = exchange_calendar.copy_exchange_calendars(database)
        except CalendarCopyError as error:
            print(f'  {type(error).__name__}: {error}')
        else:
            for line in report:
                print(f'  {line}')
        print(f'  documents updated: {database.exchange_details.updates}')

    def run(self):
        """Runs both copies.

        Returns:
            None: This method returns nothing.
        """
        self.copy([
            'nse',
            'bse',
            'mcx',
            'ncdex',
        ])
        self.copy([
            'nse',
            'bse',
        ])


if __name__ == '__main__':
    ExchangeDocumentMissingExample().run()
