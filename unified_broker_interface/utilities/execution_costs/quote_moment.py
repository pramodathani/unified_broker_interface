"""The best bid and ask of one instrument at one moment, as the stored tick history held them."""

import decimal

TWO = decimal.Decimal(2)


class QuoteMoment:
    """The touch of one instrument's order book at one moment.

    Attributes:
        time (datetime.datetime): When the tick holding this quote was received.
        bid (decimal.Decimal): The best bid.
        ask (decimal.Decimal): The best ask.
    """

    def __init__(self, time, bid, ask):
        """Builds the quote.

        Args:
            time (datetime.datetime): When the tick holding this quote was received.
            bid (decimal.Decimal): The best bid, a positive price.
            ask (decimal.Decimal): The best ask, a positive price.

        Returns:
            None: This method returns nothing.
        """
        self.time = time
        self.bid = bid
        self.ask = ask

    def mid(self):
        """The price halfway between the best bid and the best ask.

        Returns:
            decimal.Decimal: The mid-price.
        """
        return (self.bid + self.ask) / TWO

    def half_spread(self):
        """Half the gap between the best ask and the best bid, which is what crossing the spread costs against the mid-price.

        Returns:
            decimal.Decimal: Half the spread, negative only for a crossed book.
        """
        return (self.ask - self.bid) / TWO
