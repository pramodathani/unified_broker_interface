"""Reads the margin out of answers Kotak's calculator gave on 2026-09-30, and shows the error for an answer without one.

These are the real answers for one lot of NIFTY October futures sold at 22,833.70, with account identifiers removed. `read_order_margin` pick out the one figure the calibration compares; an answer that lacks it raises `MarginCalculatorError`, which the calibration logs and treats as not measured.

Notice that the future's margin is within half a percent of 167,109.41, the figure most brokers gave.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/kotak/KotakMarginCalculator/example_2_reading_recorded_answers.py
"""

from unified_broker_interface.utilities.margin_calculators.base import (
    MarginCalculatorError,
)
from unified_broker_interface.utilities.margin_calculators.kotak import (
    KotakMarginCalculator,
)

STAND_IN_LOGIN = {
    'access_token': 'stand-in-token',
    'sid': 'stand-in-session',
}
STAND_IN_SETTINGS = {
    'api_key': 'stand-in-key',
    'app_id': 'STANDIN-100',
    'client_id': '1000000001',
    'username': 'STANDIN1',
    'ucc_code': 'STANDIN1',
}


class ReadingRecordedAnswersExample:
    """Reads Kotak's recorded answers.

    Attributes:
        calculator (KotakMarginCalculator): The calculator, with stand-in credentials.
        order_answer (dict): What it answered for the NIFTY future.
    """

    def __init__(self):
        """Builds the calculator and holds the recorded answers.

        Returns:
            None: This method returns nothing.
        """
        self.calculator = KotakMarginCalculator(STAND_IN_LOGIN, STAND_IN_SETTINGS)
        self.order_answer = {
            "avlCash": "4954.190000",
            "totMrgnUsd": "167151.411000",
            "mrgnUsd": "0.000000",
            "ordMrgn": "167151.411000",
            "rmsVldtd": "NOT_OK",
            "reqdMrgn": "167151.411000",
            "avlMrgn": "4954.190000",
            "insufFund": "162197.221000",
            "stat": "Ok",
            "stCode": 200
        }

    def run(self):
        """Prints the margins read, then the error for an empty answer.

        Returns:
            None: This method returns nothing.
        """
        print(f'NIFTY future sold: {self.calculator.read_order_margin(self.order_answer)}')
        try:
            self.calculator.read_order_margin({})
        except MarginCalculatorError as error:
            print(f'An empty answer: {error}')


if __name__ == '__main__':
    ReadingRecordedAnswersExample().run()
