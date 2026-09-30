"""Decides what to do about a failed window from which `CandleError` subclass it raised.

A candle download reacts to each failure differently: it waits and retries after a throttle, stops the broker after a refused session or a block, and retires a series the broker will not serve. Anything that is not a `CandleError` at all is an unexpected failure, which is recorded against the one series. This program writes that decision as a small class, `FailureReaction`, and runs it over a list of failures, including a plain `ValueError` and a bare `CandleError`.

A bare `CandleError` falls through every subclass test, so the program shows that catching the base class is what keeps a new, unclassified failure from being mistaken for a crash. It needs no broker and no data store.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/base/CandleError/example_2_choosing_a_reaction.py
"""

from stock_brokers.instruments.historical.base import (
    CandleAuthenticationError,
    CandleBlocked,
    CandleError,
    CandleInstrumentUnknown,
    CandleThrottled,
)


class FailureReaction:
    """Chooses how a candle download reacts to one failure."""

    def reaction_to(self, failure):
        """Names the reaction a failure calls for.

        Args:
            failure (Exception): The failure a window ended with.

        Returns:
            str: What the download does next.
        """
        try:
            raise failure
        except CandleThrottled:
            return 'back off and retry the same window later'
        except (CandleAuthenticationError, CandleBlocked):
            return 'stop this broker'
        except CandleInstrumentUnknown:
            return 'retire the series'
        except CandleError:
            return 'record a candle failure against the series'
        except Exception:
            return 'record an unexpected failure against the series'


class ChoosingAReactionExample:
    """Prints the reaction to each of a list of failures.

    Attributes:
        reaction (FailureReaction): The decision being shown.
        failures (list): The failures to react to.
    """

    def __init__(self):
        """Builds the list of failures.

        Returns:
            None: This method returns nothing.
        """
        self.reaction = FailureReaction()
        self.failures = [
            CandleThrottled('Too many requests'),
            CandleAuthenticationError('Session Expired'),
            CandleBlocked('error code: 1015'),
            CandleInstrumentUnknown('invalid token'),
            CandleError('the broker answered in a shape no parser knows'),
            ValueError('could not convert string to float'),
        ]

    def run(self):
        """Prints each failure with its reaction.

        Returns:
            None: This method returns nothing.
        """
        for failure in self.failures:
            print(f'{type(failure).__name__} ({failure}): {self.reaction.reaction_to(failure)}')


if __name__ == '__main__':
    ChoosingAReactionExample().run()
