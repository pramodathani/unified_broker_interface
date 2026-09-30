"""Raises `CandleInstrumentUnknown` only for a refusal that really means the instrument is gone, not for one that means the request was wrong.

Retiring a series is permanent, so a broker module has to be careful about which refusals it turns into `CandleInstrumentUnknown`. Dhan, for example, answers `Input_Exception` both for an instrument it will not serve and for a window that spans too many days; only the first is a dead instrument, and the second must stay an ordinary error so the series is retried with a narrower window. This program writes that distinction as a small classifier and runs it over two Dhan-shaped messages.

The messages are canned copies of what Dhan returns, so no request leaves the machine.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/base/CandleInstrumentUnknown/example_2_telling_a_dead_instrument_from_a_bad_request.py
"""

from stock_brokers.instruments.historical.base import (
    CandleInstrumentUnknown,
)


class DhanStyleClassifier:
    """Decides whether a Dhan-style refusal means the instrument is gone."""

    def raise_for(self, message):
        """Raises the failure a refusal stands for.

        Args:
            message (str): The broker's error text.

        Returns:
            None: This method returns nothing.

        Raises:
            CandleInstrumentUnknown: When the refusal means the broker will not serve the instrument.
            RuntimeError: For any other refusal, which is retried later.
        """
        if 'Input_Exception' in message and 'can be fetched for' not in message:
            raise CandleInstrumentUnknown(message)
        raise RuntimeError(message)


class TellingADeadInstrumentFromABadRequestExample:
    """Classifies two refusals and prints which would retire a series.

    Attributes:
        classifier (DhanStyleClassifier): The classifier being shown.
        messages (list): The canned refusals.
    """

    def __init__(self):
        """Builds the classifier and the refusals.

        Returns:
            None: This method returns nothing.
        """
        self.classifier = DhanStyleClassifier()
        self.messages = [
            "('Input_Exception', 'Missing required fields')",
            "('Input_Exception', 'Data for Intraday Charts can be fetched for 90 days at a time')",
        ]

    def run(self):
        """Classifies each refusal and prints the outcome.

        Returns:
            None: This method returns nothing.
        """
        for message in self.messages:
            try:
                self.classifier.raise_for(message)
            except CandleInstrumentUnknown:
                print(f'{message}: CandleInstrumentUnknown, retire the series')
            except RuntimeError:
                print(f'{message}: an ordinary error, retry the series later')


if __name__ == '__main__':
    TellingADeadInstrumentFromABadRequestExample().run()
