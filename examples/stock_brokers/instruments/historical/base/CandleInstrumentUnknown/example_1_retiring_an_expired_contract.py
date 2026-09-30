"""Raises `CandleInstrumentUnknown` for a contract the broker no longer knows, and retires its series instead of retrying it.

Kite answers `invalid token` for an instrument that has left its instrument dump, which is usually an expired contract. No amount of retrying changes that answer, so a broker module raises `CandleInstrumentUnknown` and the candle download marks the series retired. This program has a stand-in broker that knows only live tokens, and a small queue that retires every series the broker does not know.

The stand-in broker answers from memory, so no request leaves the machine.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/base/CandleInstrumentUnknown/example_1_retiring_an_expired_contract.py
"""

from stock_brokers.instruments.historical.base import (
    CandleError,
    CandleInstrumentUnknown,
)


class StandInBroker:
    """A stand-in broker that serves only the tokens in its current instrument dump.

    Attributes:
        live_tokens (set): The tokens the broker still serves.
    """

    def __init__(self):
        """Builds the broker with two live tokens.

        Returns:
            None: This method returns nothing.
        """
        self.live_tokens = {
            '738561',
            '13368834',
        }

    def fetch(self, token):
        """Fetches one window of candles.

        Args:
            token (str): The instrument token.

        Returns:
            int: How many candles came back.

        Raises:
            CandleInstrumentUnknown: When the token is not in the dump.
        """
        if token not in self.live_tokens:
            raise CandleInstrumentUnknown(f'invalid token: {token}')
        return 250


class RetiringAnExpiredContractExample:
    """Fetches three series and retires the one the broker does not know.

    Attributes:
        broker (StandInBroker): The stand-in broker.
        retired (dict): Token to the reason it was retired.
    """

    def __init__(self):
        """Builds the broker and an empty list of retired series.

        Returns:
            None: This method returns nothing.
        """
        self.broker = StandInBroker()
        self.retired = {}

    def run(self):
        """Fetches each series and prints what became of it.

        Returns:
            None: This method returns nothing.
        """
        tokens = [
            '738561',
            '12094466',
            '13368834',
        ]
        for token in tokens:
            try:
                candles = self.broker.fetch(token)
            except CandleInstrumentUnknown as error:
                self.retired[token] = str(error)
                print(f'{token}: retired')
                continue
            print(f'{token}: {candles} candles')
        print(f'Retired series and why: {self.retired}')
        print(f'CandleInstrumentUnknown is a CandleError: {issubclass(CandleInstrumentUnknown, CandleError)}')


if __name__ == '__main__':
    RetiringAnExpiredContractExample().run()
