"""Shows `MarginCalculatorError` raised for Wisdom Capital's crude oil answer of 2026-09-30, which said the margin was zero.

A `MarginCalculatorError` means a broker's calculator could not be asked, or its answer could not be read as a margin. The calibration catches it for that one reference order, logs it, and leaves the broker's figure for that category unchanged. `amount` raises it for a figure that is missing, not a number, or not above zero, because a zero margin for one lot of crude oil cannot be true.

Notice that the message names the broker and the field, so the log line says exactly what was wrong.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/base/MarginCalculatorError/example_1_an_answer_that_is_not_a_margin.py
"""

from unified_broker_interface.utilities.margin_calculators.base import (
    MarginCalculatorError,
)
from unified_broker_interface.utilities.margin_calculators.wisdom_capital import (
    WisdomCapitalMarginCalculator,
)


class AnAnswerThatIsNotAMarginExample:
    """Reads three answers, two of which are not margins.

    Attributes:
        calculator (WisdomCapitalMarginCalculator): The calculator, with stand-in credentials.
        answers (list): `(description, answer)` tuples.
    """

    def __init__(self):
        """Builds the calculator and the answers.

        Returns:
            None: This method returns nothing.
        """
        login = {
            'access_token': 'stand-in-token',
        }
        settings = {
            'ucc_code': 'STANDIN1',
        }
        self.calculator = WisdomCapitalMarginCalculator(login, settings)
        self.answers = [
            ('NIFTY future sold', {'result': {'brokerageDeatils': {'IsValid': True, 'MarginRequired': 183820.351}}}),
            ('crude oil future bought', {'result': {'brokerageDeatils': {'IsValid': True, 'MarginRequired': 0}}}),
            ('a refusal', {'type': 'error', 'result': None}),
        ]

    def run(self):
        """Reads each answer and prints the margin or the error.

        Returns:
            None: This method returns nothing.
        """
        for description, answer in self.answers:
            try:
                print(f'{description}: {self.calculator.read_order_margin(answer)}')
            except MarginCalculatorError as error:
                print(f'{description}: {type(error).__name__}: {error}')


if __name__ == '__main__':
    AnAnswerThatIsNotAMarginExample().run()
