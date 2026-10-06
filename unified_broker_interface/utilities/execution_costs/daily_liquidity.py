"""How much an instrument's price moves in a day and how much of it trades, from its recent daily bars."""

import decimal
import statistics

FEWEST_DAYS = 10
DAYS_USED = 20


class DailyLiquidity:
    """An instrument's daily volatility and average daily volume over its last `DAYS_USED` daily bars.

    Volatility is the sample standard deviation of the daily log returns of the closing price, as a fraction of the price: 0.02 means a typical day moves the price about 2%. Both figures need at least `FEWEST_DAYS` days.

    Attributes:
        closes (list): The closing prices (decimal.Decimal), oldest first.
        volumes (list): The daily volumes in units (int), oldest first.
    """

    def __init__(self, closes, volumes):
        """Builds the figures from the most recent bars given.

        Args:
            closes (list): Closing prices (decimal.Decimal), oldest first; only the last `DAYS_USED` plus one are kept, so there are `DAYS_USED` returns.
            volumes (list): Daily volumes in units (int), oldest first; only the last `DAYS_USED` are kept.

        Returns:
            None: This method returns nothing.
        """
        self.closes = list(closes)[-(DAYS_USED + 1):]
        self.volumes = list(volumes)[-DAYS_USED:]

    def volatility(self):
        """The standard deviation of the daily log returns.

        Returns:
            decimal.Decimal | None: A fraction of the price, or None with fewer than `FEWEST_DAYS` returns or a closing price that is not positive.
        """
        returns = []
        for index in range(1, len(self.closes)):
            before = self.closes[index - 1]
            after = self.closes[index]
            if before is None or after is None or before <= 0 or after <= 0:
                return None
            returns.append((decimal.Decimal(after) / decimal.Decimal(before)).ln())
        if len(returns) < FEWEST_DAYS:
            return None
        return statistics.stdev(returns)

    def average_volume(self):
        """The mean daily volume.

        Returns:
            decimal.Decimal | None: Units, or None with fewer than `FEWEST_DAYS` days or no volume at all.
        """
        volumes = []
        for volume in self.volumes:
            if volume is not None:
                volumes.append(decimal.Decimal(volume))
        if len(volumes) < FEWEST_DAYS:
            return None
        average = statistics.mean(volumes)
        if average <= 0:
            return None
        return average
