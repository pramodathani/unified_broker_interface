"""How far an instrument's price usually moves against a position within a few seconds, from its recent ticks."""

import datetime
import decimal
import math

DEFAULT_HORIZON_SECONDS = 5
DEFAULT_WINDOW_MINUTES = 30
DEFAULT_PERCENTILE = 90
MINIMUM_SAMPLES = 30
LOOKBACK_DAYS = 5

TICKS_QUERY = """
SELECT "time", bid1_price, ask1_price
FROM unified.ticks
WHERE instrument_id = %s
    AND "time" >= (
        SELECT max("time") - %s
        FROM unified.ticks
        WHERE instrument_id = %s
            AND "time" >= %s
    )
    AND bid1_price > 0
    AND ask1_price > 0
ORDER BY "time"
"""


class PriceFlicker:
    """The ordinary flicker of the price a stop watches: the move against the position that the price makes within a few seconds, and then often undoes.

    A stop moved to its tripwire the moment the price reaches the tripwire is fired by the next ordinary wobble. The flicker is how far that wobble usually goes. For a bought position, whose stop sells on the bid, it is how far the bid falls below each tick's bid within the next `horizon_seconds`; for a sold position, whose stop buys on the ask, how far the ask rises. The percentile of those moves, the 90th by default, is the move nine ticks in ten stayed within, so a stop placed that far beyond the tripwire is not fired by nine wobbles in ten.

    Attributes:
        opening_side (str): `BUY` for a bought position, which watches the bid, or `SELL` for a sold one, which watches the ask.
        horizon_seconds (int): How far ahead of each tick the move is measured.
        samples (list): Tuples of time (datetime.datetime) and price (decimal.Decimal), oldest first.
    """

    def __init__(self, opening_side, horizon_seconds=DEFAULT_HORIZON_SECONDS, samples=None):
        """Builds the flicker from samples of the price the stop watches.

        Args:
            opening_side (str): `BUY` or `SELL`, the side that opened the position.
            horizon_seconds (int): How far ahead of each tick the move is measured.
            samples (list | None): Tuples of time and price, oldest first, or None for none.

        Returns:
            None: This method returns nothing.

        Raises:
            ValueError: When the opening side is neither `BUY` nor `SELL`, or the horizon is not positive.
        """
        if opening_side not in ('BUY', 'SELL'):
            raise ValueError(f'The opening side must be BUY or SELL: {opening_side=}')
        if horizon_seconds <= 0:
            raise ValueError(f'The horizon must be positive: {horizon_seconds=}')
        self.opening_side = opening_side
        self.horizon_seconds = horizon_seconds
        self.samples = list(samples or [])

    def read(self, connect, instrument_id, now, window_minutes=DEFAULT_WINDOW_MINUTES):
        """Replaces the samples with the last minutes of the instrument's stored ticks, from the latest session that has any.

        Args:
            connect (Callable): Opens a PostgreSQL connection, such as `configurations.get_postgres`.
            instrument_id (str): The instrument.
            now (datetime.datetime): The moment to look back from.
            window_minutes (int): How many minutes before the latest tick to read.

        Returns:
            None: This method returns nothing.

        Raises:
            psycopg2.Error: When the database cannot be read.
        """
        oldest = now - datetime.timedelta(days=LOOKBACK_DAYS)
        window = datetime.timedelta(minutes=window_minutes)
        connection = connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(TICKS_QUERY, (instrument_id, window, instrument_id, oldest))
                fetched = cursor.fetchall()
            connection.rollback()
        finally:
            connection.close()
        samples = []
        for moment, bid, ask in fetched:
            if self.opening_side == 'BUY':
                samples.append((moment, decimal.Decimal(bid)))
            else:
                samples.append((moment, decimal.Decimal(ask)))
        self.samples = samples

    def moves(self):
        """The move against the position from each sample to the worst price within the horizon after it.

        Returns:
            list: One decimal.Decimal per sample that has a later sample within the horizon, zero when the price did not move against the position, sorted.
        """
        result = []
        horizon = datetime.timedelta(seconds=self.horizon_seconds)
        count = len(self.samples)
        for index in range(count):
            moment, price = self.samples[index]
            worst = None
            later = index + 1
            while later < count and self.samples[later][0] - moment <= horizon:
                later_price = self.samples[later][1]
                if worst is None:
                    worst = later_price
                elif self.opening_side == 'BUY' and later_price < worst:
                    worst = later_price
                elif self.opening_side == 'SELL' and later_price > worst:
                    worst = later_price
                later = later + 1
            if worst is None:
                continue
            if self.opening_side == 'BUY':
                move = price - worst
            else:
                move = worst - price
            if move < 0:
                move = decimal.Decimal(0)
            result.append(move)
        result.sort()
        return result

    def distance(self, percentile=DEFAULT_PERCENTILE):
        """The flicker: a nearest-rank percentile of the moves.

        Args:
            percentile (int): Which percentile, from 1 to 100.

        Returns:
            decimal.Decimal | None: The distance in price, or None when fewer than `MINIMUM_SAMPLES` moves were measured.
        """
        moves = self.moves()
        if len(moves) < MINIMUM_SAMPLES:
            return None
        rank = math.ceil(percentile / 100 * len(moves))
        return moves[max(rank, 1) - 1]
