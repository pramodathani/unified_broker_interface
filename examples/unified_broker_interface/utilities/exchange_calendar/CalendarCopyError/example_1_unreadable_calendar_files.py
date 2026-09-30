"""Catches the `CalendarCopyError` raised when the yearly calendar files cannot be copied as they stand.

`read_calendars` reads every `<year>.yaml` holiday file in a folder and merges them. It raises `CalendarCopyError` in two cases this program shows: the folder holds no calendar files at all, and a holiday says it closes a session that does not exist. Because the error is raised while reading, before anything is written, the `import-api-details --calendars-only` command stops with the message and MongoDB is left as it was.

The first case reads a folder that does not exist, which looks the same as an empty one. The second writes one small calendar file into a temporary folder, with an NSE equity holiday whose `closed` value is `afternoon` instead of `all`, `morning` or `evening`. Only the file's name appears in the message, so the temporary folder's path is never printed. Nothing touches MongoDB.

Notice that the error is an ordinary `Exception` subclass whose message names the file, the exchange, the calendar, the date and the bad value.

Run it from the project root:

    python examples/unified_broker_interface/utilities/exchange_calendar/CalendarCopyError/example_1_unreadable_calendar_files.py
"""

import pathlib
import tempfile

from unified_broker_interface.utilities import exchange_calendar
from unified_broker_interface.utilities.exchange_calendar import (
    CalendarCopyError,
)

BAD_CALENDAR = """year: 2027
holidays:
  nse:
    equity:
      - date: 2027-01-26
        closed: afternoon
        name: Republic Day
"""


class UnreadableCalendarFilesExample:
    """Reads a missing folder and a folder holding a bad file, catching the error each time.

    Attributes:
        missing_directory (str): A folder that holds no calendar files.
    """

    def __init__(self):
        """Names the folder that holds no calendar files.

        Returns:
            None: This method returns nothing.
        """
        self.missing_directory = 'examples/no_calendar_files_here'

    def read(self, label, directory):
        """Reads the calendars in a folder and prints the error, or how many years were read.

        Args:
            label (str): What the folder is, for the printout.
            directory (str | pathlib.Path): The folder to read.

        Returns:
            None: This method returns nothing.
        """
        try:
            holidays, special_sessions, years = exchange_calendar.read_calendars(directory)
        except CalendarCopyError as error:
            print(f'{label}: {type(error).__name__}: {error}')
            print(f'  is an Exception: {isinstance(error, Exception)}')
            return
        print(f'{label}: read years {years}')

    def run(self):
        """Reads the missing folder, then a temporary folder with one bad file.

        Returns:
            None: This method returns nothing.
        """
        self.read('Missing folder', self.missing_directory)
        with tempfile.TemporaryDirectory() as directory:
            pathlib.Path(directory, '2027.yaml').write_text(BAD_CALENDAR)
            self.read('Bad closure kind', directory)


if __name__ == '__main__':
    UnreadableCalendarFilesExample().run()
