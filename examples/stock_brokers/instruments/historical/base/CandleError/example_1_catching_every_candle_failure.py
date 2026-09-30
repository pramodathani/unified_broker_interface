"""Catches every kind of candle download failure with the one base class, `CandleError`.

`CandleError` is the parent of the four failures a candle download tells apart: a throttle, a refused session, a block on the whole client and an instrument the broker will not serve. Code that only needs to know that a window failed for a reason the download understands can catch `CandleError`, and code that must react differently to each kind catches the subclasses.

This program raises one of each subclass in turn, catches it as `CandleError`, and prints the class, its message and its place in the hierarchy. It needs no broker and no data store.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/base/CandleError/example_1_catching_every_candle_failure.py
"""

from stock_brokers.instruments.historical.base import (
    CandleAuthenticationError,
    CandleBlocked,
    CandleError,
    CandleInstrumentUnknown,
    CandleThrottled,
)


class CatchingEveryCandleFailureExample:
    """Raises each candle failure and catches it as a `CandleError`.

    Attributes:
        failures (list): The exceptions to raise, one of each subclass.
    """

    def __init__(self):
        """Builds one failure of each kind, with the message a broker might have caused.

        Returns:
            None: This method returns nothing.
        """
        self.failures = [
            CandleThrottled('Too many requests'),
            CandleAuthenticationError('Incorrect `api_key` or `access_token`.'),
            CandleBlocked('error code: 1015'),
            CandleInstrumentUnknown('invalid token'),
        ]

    def raise_failure(self, failure):
        """Raises one failure, as a broker module's `fetch_candles` would.

        Args:
            failure (CandleError): The failure to raise.

        Returns:
            None: This method returns nothing.

        Raises:
            CandleError: Always, the failure given.
        """
        raise failure

    def run(self):
        """Raises and catches each failure, then prints the class hierarchy.

        Returns:
            None: This method returns nothing.
        """
        for failure in self.failures:
            try:
                self.raise_failure(failure)
            except CandleError as error:
                print(f'Caught {type(error).__name__} as CandleError: {error}')
        print(f'CandleError is an Exception: {issubclass(CandleError, Exception)}')
        subclass_names = []
        for subclass in CandleError.__subclasses__():
            subclass_names.append(subclass.__name__)
        print(f'Classes that inherit from CandleError directly: {subclass_names}')


if __name__ == '__main__':
    CatchingEveryCandleFailureExample().run()
