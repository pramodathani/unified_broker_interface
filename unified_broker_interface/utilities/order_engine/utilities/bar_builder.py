"""Building candles out of the one-second price ticks the engine already reads."""

import decimal

MOST_KEPT_BARS = 50


class BarBuilder:
    """Turns a stream of prices into closed bars, keeping its state on the parent.

    Two order types need candles: one exits when a bar *closes* beyond a level, so that a brief wick does not stop it out, and one measures volatility from the range of recent bars. Neither can be built from a price alone.

    The candles are built here rather than read from the price history tables, and the trade-off is worth being clear about. Reading `unified.price_history` would give proper bars going back years, at the cost of a database query inside the order path and a dependency on the daily history job having run. Building them from the engine's own ticks costs nothing and gives bars that only start when the order was placed.

    **So a bar-based order knows nothing about the market before it existed.** An order placed at eleven o'clock asking for fifteen-minute bars has no bars at all until quarter past, and no average of ten of them until half past two. Every type built on this says what it does in the meantime, rather than pretending to a history it does not have.

    The bars are also built from samples rather than from trades. A one-second tick carries the last traded price at that moment, so a high that happened and was traded through between two ticks is missed. For a fifteen-minute bar sampled nine hundred times that is a small error; for a one-minute bar on an instrument that trades once a minute it is not, and the shorter the bar the less this is worth trusting.

    Everything is kept as text in the parent's parameters, so it survives a restart and goes through JSON without a float rounding a price.
    """

    def __init__(self, parameters, bar_seconds):
        """Builds the builder over one parent's stored state.

        Args:
            parameters (dict): The parent's parameters, which this reads and returns updates for.
            bar_seconds (float): How long one bar lasts.

        Returns:
            None: This method returns nothing.
        """
        self.parameters = parameters
        self.bar_seconds = bar_seconds

    def bar_start(self, now):
        """The start of the bar a moment falls in, aligned to the bar length.

        Aligning to the length rather than to when the order was placed is what makes two orders on the same instrument agree about where the bars are, and what makes a fifteen-minute bar start at a quarter past the hour as anybody reading a chart would expect.

        Args:
            now (float): The Unix time.

        Returns:
            float: The bar's start.
        """
        return (now // self.bar_seconds) * self.bar_seconds

    def add(self, price, now):
        """Adds one price, and returns the bar that just closed if one did.

        Args:
            price (decimal.Decimal): The price seen.
            now (float): The Unix time of the tick.

        Returns:
            dict | None: The closed bar, with `high`, `low` and `close` as `decimal.Decimal`, or None when the current bar is still open.
        """
        started = self.bar_start(now)
        current = self.parameters.get('bar_started_at')
        closed = None
        if current is not None and started > current:
            closed = self.current_bar()
            if closed is not None:
                self.keep(closed)
            current = None
        if current is None:
            self.parameters['bar_started_at'] = started
            self.parameters['bar_high'] = str(price)
            self.parameters['bar_low'] = str(price)
            self.parameters['bar_close'] = str(price)
            return closed
        high = self.number('bar_high')
        low = self.number('bar_low')
        if high is None or price > high:
            self.parameters['bar_high'] = str(price)
        if low is None or price < low:
            self.parameters['bar_low'] = str(price)
        self.parameters['bar_close'] = str(price)
        return closed

    def current_bar(self):
        """The bar being built, as a dictionary of numbers.

        Returns:
            dict | None: The bar, or None when it is not readable.
        """
        high = self.number('bar_high')
        low = self.number('bar_low')
        close = self.number('bar_close')
        if high is None or low is None or close is None:
            return None
        return {
            'high': high,
            'low': low,
            'close': close,
        }

    def number(self, name):
        """One stored price, as a number.

        Args:
            name (str): The parameter's name.

        Returns:
            decimal.Decimal | None: The price, or None when it is missing or unreadable.
        """
        text = self.parameters.get(name)
        if text is None:
            return None
        try:
            return decimal.Decimal(str(text))
        except decimal.InvalidOperation:
            return None

    def keep(self, bar):
        """Remembers a closed bar, dropping the oldest once there are enough.

        Args:
            bar (dict): The closed bar.

        Returns:
            None: This method returns nothing.
        """
        kept = list(self.parameters.get('closed_bars') or [])
        kept.append([
            str(bar['high']),
            str(bar['low']),
            str(bar['close']),
        ])
        self.parameters['closed_bars'] = kept[-MOST_KEPT_BARS:]

    def closed_bars(self):
        """The bars that have closed since this order was placed, oldest first.

        Returns:
            list: One dictionary per bar, with `high`, `low` and `close` as `decimal.Decimal`.
        """
        bars = []
        for entry in self.parameters.get('closed_bars') or []:
            if not isinstance(entry, list) or len(entry) != 3:
                continue
            try:
                bars.append({
                    'high': decimal.Decimal(str(entry[0])),
                    'low': decimal.Decimal(str(entry[1])),
                    'close': decimal.Decimal(str(entry[2])),
                })
            except decimal.InvalidOperation:
                continue
        return bars

    def average_true_range(self, periods):
        """The average of the last `periods` bars' true ranges, once there are that many.

        The true range is the greater of the bar's own high-to-low span and the distance from the previous bar's close to this bar's high or low, which is what counts a gap as movement rather than ignoring it.

        Args:
            periods (int): How many bars to average.

        Returns:
            decimal.Decimal | None: The average, or None when fewer than `periods` bars have closed.
        """
        bars = self.closed_bars()
        if len(bars) < periods + 1:
            return None
        ranges = []
        for index in range(len(bars) - periods, len(bars)):
            bar = bars[index]
            previous_close = bars[index - 1]['close']
            spans = [
                bar['high'] - bar['low'],
                abs(bar['high'] - previous_close),
                abs(bar['low'] - previous_close),
            ]
            ranges.append(max(spans))
        return sum(ranges) / len(ranges)
