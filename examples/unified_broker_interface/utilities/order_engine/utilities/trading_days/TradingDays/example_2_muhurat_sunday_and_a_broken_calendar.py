"""Shows a Sunday that trades because of Muhurat trading, and what happens when the calendar says nothing ever trades.

Diwali's Muhurat session makes Sunday 8 November 2026 a trading day on NSE, even though every other Sunday is shut. This program asks the real `TradingDays`, over the repository's calendar files, about the days around it, and shows that the next trading day after Saturday 7 November is that Sunday rather than Monday.

It then builds a second `TradingDays` over a small stand-in session gate that answers "closed" for every day, as a missing or broken set of calendar files would. `next_trading_day` looks thirty days ahead and then raises `ValueError`, because an order waiting for a trading day that never comes is a configuration fault to report, not a thing to wait on. The stand-in also records which exchange and session it was asked about, which shows how the segment is split before the gate is asked.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/trading_days/TradingDays/example_2_muhurat_sunday_and_a_broken_calendar.py
"""

import datetime

from unified_broker_interface.utilities.order_engine.utilities.trading_days import (
    TradingDays,
)


class AlwaysClosedGate:
    """A stand-in session gate whose calendar has no trading days at all.

    Attributes:
        questions (list): Every (exchange, day number) pair it was asked about.
    """

    def __init__(self):
        """Builds the stand-in with no questions asked.

        Returns:
            None: This method returns nothing.
        """
        self.questions = []

    def is_trading_day(self, exchange, session, day_number):
        """Answers that the day does not trade, and remembers the question.

        Args:
            exchange (str): The exchange, such as `nse`.
            session (object): The session window, unused here.
            day_number (int): Whole days since 1 January 1970.

        Returns:
            bool: Always False.
        """
        self.questions.append((exchange, day_number))
        return False


class MuhuratSundayExample:
    """Prints the days around Diwali and the failure over an empty calendar.

    Attributes:
        trading_days (TradingDays): A reader over the repository's calendar files.
        broken_gate (AlwaysClosedGate): The stand-in gate.
        broken_days (TradingDays): A reader over the stand-in gate.
    """

    def __init__(self):
        """Builds both readers.

        Returns:
            None: This method returns nothing.
        """
        self.trading_days = TradingDays()
        self.broken_gate = AlwaysClosedGate()
        self.broken_days = TradingDays(self.broken_gate)

    def run(self):
        """Prints the answers from both readers.

        Returns:
            None: This method returns nothing.
        """
        for day_of_month in range(6, 11):
            day = datetime.date(2026, 11, day_of_month)
            answer = self.trading_days.is_trading_day('nse_equities', day)
            print(f'{day} {day.strftime("%a")}: trades {answer}')
        saturday = datetime.date(2026, 11, 7)
        following = self.trading_days.next_trading_day('nse_equities', saturday)
        print(f'Next trading day after {saturday}: {following} {following.strftime("%a")}')
        try:
            self.broken_days.next_trading_day('nse_equities', saturday)
        except ValueError as error:
            print(f'ValueError: {error}')
        print(f'Questions the stand-in gate was asked: {len(self.broken_gate.questions)}')
        print(f'First question: {self.broken_gate.questions[0]}')


if __name__ == '__main__':
    MuhuratSundayExample().run()
