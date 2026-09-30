"""Shows the two cases where the loss lockout lets an order through even on a bad day: no limit set, and funds that cannot be read.

The lockout is off unless a positive limit is configured, so a limit of zero never refuses anything, however large the loss. And when the funds document cannot be read, because Redis failed, the key is missing or its text is not JSON, the lockout lets the order through and logs a warning rather than halting all trading.

Two small stand-ins replace the Redis client: one that returns whatever text it was given, and one whose `get` raises a connection error. A third stand-in replaces the logger and prints each warning, so the program's output shows what an operator would see in the engine's log.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/loss_lockout/LossLockout/example_2_switched_off_or_unreadable.py
"""

import json

from unified_broker_interface.utilities.order_engine.utilities.loss_lockout import (
    LossLockout,
)


class TextRedis:
    """A stand-in for the Redis client whose every `get` returns one fixed text.

    Attributes:
        text (str | None): What `get` returns.
    """

    def __init__(self, text):
        """Builds the stand-in.

        Args:
            text (str | None): What `get` returns.

        Returns:
            None: This method returns nothing.
        """
        self.text = text

    def get(self, key):
        """Returns the fixed text whatever the key.

        Args:
            key (str): The key, which is ignored.

        Returns:
            str | None: The fixed text.
        """
        return self.text


class BrokenRedis:
    """A stand-in for a Redis client whose server has gone away."""

    def get(self, key):
        """Fails the way a dropped connection does.

        Args:
            key (str): The key being read.

        Returns:
            None: This method never returns.

        Raises:
            ConnectionError: Always.
        """
        raise ConnectionError('Connection refused')


class PrintingLogger:
    """A stand-in for a logger that prints each warning."""

    def warning(self, message):
        """Prints a warning.

        Args:
            message (str): The warning.

        Returns:
            None: This method returns nothing.
        """
        print(f'  WARNING {message}')


class SwitchedOffOrUnreadableExample:
    """Asks several lockouts for a refusal where none should be given.

    Attributes:
        logger (PrintingLogger): The stand-in logger.
        heavy_loss (str): A funds document showing a 90,000 rupee loss.
    """

    def __init__(self):
        """Builds the logger and the losing funds document.

        Returns:
            None: This method returns nothing.
        """
        self.logger = PrintingLogger()
        document = {
            'pnl': {
                'realized': -60000.0,
                'unrealized': -30000.0,
            },
        }
        self.heavy_loss = json.dumps(document)

    def run(self):
        """Prints each lockout's reading and answer.

        Returns:
            None: This method returns nothing.
        """
        switched_off = LossLockout(TextRedis(self.heavy_loss), 0, self.logger)
        print('Limit of zero on a 90,000 loss:')
        print(f'  Configured: {switched_off.is_configured()}')
        print(f'  Refusal: {switched_off.refusal_reason()}')
        broken = LossLockout(BrokenRedis(), 5000.0, self.logger)
        print('Redis unreachable:')
        print(f'  Day profit: {broken.day_profit()}')
        print(f'  Refusal: {broken.refusal_reason()}')
        missing = LossLockout(TextRedis(None), 5000.0, self.logger)
        print('Funds key missing:')
        print(f'  Day profit: {missing.day_profit()}')
        garbled = LossLockout(TextRedis('not json'), 5000.0, self.logger)
        print('Funds text is not JSON:')
        print(f'  Day profit: {garbled.day_profit()}')
        print(f'  Refusal: {garbled.refusal_reason()}')


if __name__ == '__main__':
    SwitchedOffOrUnreadableExample().run()
