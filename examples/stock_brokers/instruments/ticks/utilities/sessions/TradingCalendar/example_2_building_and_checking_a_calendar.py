"""Builds calendars without the repository's files: an empty one, one from tables, and one from a file with a mistake.

`TradingCalendar.empty` gives a calendar with no holidays at all, which is what the offline suites use when a real calendar would get in the way; every weekday then trades. A calendar can also be built directly from its two tables, which is how a test pins down one closure without a file.

`TradingCalendar.load` checks the files it reads: a closure must be "all", "morning" or "evening". The program writes a one-holiday calendar file for an imaginary year into a temporary folder with the closure kind misspelt, and shows the `ValueError` naming the file, exchange, calendar and date. Only the file's name is printed, never the temporary path, so the output is the same on every run. No data store is involved.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/utilities/sessions/TradingCalendar/example_2_building_and_checking_a_calendar.py
"""

import datetime
import pathlib
import tempfile

from stock_brokers.instruments.ticks.utilities.sessions import (
    TradingCalendar,
)

BAD_FILE = """year: 2027
holidays:
  nse:
    equity:
      - {date: 2027-01-26, closed: allday, name: "Republic Day"}
"""


class BuildingCalendarsExample:
    """Builds an empty calendar, a calendar from tables, and tries to load a bad file.

    Attributes:
        republic_day (datetime.date): The holiday used throughout.
    """

    def __init__(self):
        """Fixes the date asked about.

        Returns:
            None: This method returns nothing.
        """
        self.republic_day = datetime.date(2027, 1, 26)

    def run(self):
        """Prints what each calendar says about the date.

        Returns:
            None: This method returns nothing.
        """
        empty = TradingCalendar.empty()
        print(f'Empty calendar: closure {empty.closure("nse", "equity", self.republic_day)}, special session {empty.special_session("nse", "equity", self.republic_day)}, years {empty.years}')
        closures = {
            (
                'nse',
                'equity',
            ): {
                self.republic_day: 'all',
            },
        }
        special_sessions = {
            (
                'nse',
                'equity',
            ): {
                datetime.date(2027, 10, 31): (
                    18 * 3600,
                    19 * 3600 + 15 * 60,
                ),
            },
        }
        years = (
            2027,
        )
        built = TradingCalendar(closures, special_sessions, years)
        print(f'Built calendar: nse equity on {self.republic_day} closed {built.closure("nse", "equity", self.republic_day)}')
        print(f'Built calendar: nse currency on {self.republic_day} closed {built.closure("nse", "currency", self.republic_day)}')
        print(f'Built calendar: special session on 2027-10-31 {built.special_session("nse", "equity", datetime.date(2027, 10, 31))}')
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / '2027.yaml'
            path.write_text(BAD_FILE)
            try:
                TradingCalendar.load(directory)
            except ValueError as error:
                print(f'Loading the misspelt file refused: {error}')


if __name__ == '__main__':
    BuildingCalendarsExample().run()
