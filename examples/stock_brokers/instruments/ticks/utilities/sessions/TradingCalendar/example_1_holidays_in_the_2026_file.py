"""Loads the exchanges' 2026 calendar and asks what is closed on a few dates.

`TradingCalendar.load` reads every `<year>.yaml` file in `stock_brokers/instruments/ticks/utilities/calendars/`, which were generated from each exchange's own publication. Holidays are kept per exchange and per calendar, because one exchange's segments do not close together: on Ganesh Chaturthi (Monday 2026-09-14) NSE equities are closed all day while MCX commodities close only their morning session, and on New Year's Day MCX closes only its evening. A currency-only bank holiday closes the currency calendar while equities trade.

`closure` answers "all", "morning", "evening" or None for a date that is not listed. `special_session` answers the window of a special session, such as the Diwali Muhurat session on Sunday 2026-11-08, as seconds after midnight India time; the program also prints it as clock times. The Muhurat timings had not been notified when the file was written, so it holds the whole day open, 09:00 to 23:59:59, on every exchange and calendar. The files are part of the repository, so the program reads nothing outside it and needs no data store.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/utilities/sessions/TradingCalendar/example_1_holidays_in_the_2026_file.py
"""

import datetime

from stock_brokers.instruments.ticks.utilities.sessions import (
    TradingCalendar,
)


class HolidaysIn2026Example:
    """Asks the loaded 2026 calendar about closures and special sessions.

    Attributes:
        calendar (TradingCalendar): The calendar loaded from the repository's files.
    """

    def __init__(self):
        """Loads the calendar.

        Returns:
            None: This method returns nothing.
        """
        self.calendar = TradingCalendar.load()

    def clock(self, seconds):
        """Formats seconds after midnight as a clock time.

        Args:
            seconds (int): Seconds after midnight.

        Returns:
            str: The time as HH:MM.
        """
        hours = seconds // 3600
        minutes = seconds % 3600 // 60
        return f'{hours:02d}:{minutes:02d}'

    def print_closure(self, exchange, calendar_name, day):
        """Prints what of a day is closed for one exchange's calendar.

        Args:
            exchange (str): The canonical exchange.
            calendar_name (str): "equity", "currency" or "commodity".
            day (datetime.date): The date.

        Returns:
            None: This method returns nothing.
        """
        closed = self.calendar.closure(exchange, calendar_name, day)
        print(f'{day} {exchange} {calendar_name}: closed {closed}')

    def print_special_session(self, exchange, calendar_name, day):
        """Prints the special session held on a day, if any.

        Args:
            exchange (str): The canonical exchange.
            calendar_name (str): "equity", "currency" or "commodity".
            day (datetime.date): The date.

        Returns:
            None: This method returns nothing.
        """
        window = self.calendar.special_session(exchange, calendar_name, day)
        if window is None:
            print(f'{day} {exchange} {calendar_name}: no special session')
            return
        print(f'{day} {exchange} {calendar_name}: special session {window}, {self.clock(window[0])} to {self.clock(window[1])}')

    def run(self):
        """Prints closures and special sessions for chosen dates.

        Returns:
            None: This method returns nothing.
        """
        print(f'Years loaded: {self.calendar.years}')
        ganesh_chaturthi = datetime.date(2026, 9, 14)
        self.print_closure('nse', 'equity', ganesh_chaturthi)
        self.print_closure('mcx', 'commodity', ganesh_chaturthi)
        self.print_closure('ncdex', 'commodity', ganesh_chaturthi)
        self.print_closure('mcx', 'commodity', datetime.date(2026, 1, 1))
        bank_holiday = datetime.date(2026, 8, 26)
        self.print_closure('nse', 'currency', bank_holiday)
        self.print_closure('nse', 'equity', bank_holiday)
        self.print_closure('nse', 'equity', datetime.date(2026, 9, 15))
        muhurat = datetime.date(2026, 11, 8)
        self.print_special_session('nse', 'equity', muhurat)
        self.print_special_session('mcx', 'commodity', muhurat)
        self.print_special_session('nse', 'currency', muhurat)


if __name__ == '__main__':
    HolidaysIn2026Example().run()
