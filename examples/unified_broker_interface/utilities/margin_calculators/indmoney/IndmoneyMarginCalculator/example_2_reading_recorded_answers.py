"""Reads the margin out of answers INDmoney's calculator gave on 2026-09-30, and shows the error for an answer without one.

These are the real answers for one lot of NIFTY October futures sold at 22,833.70, with account identifiers removed. `read_order_margin` pick out the one figure the calibration compares; an answer that lacks it raises `MarginCalculatorError`, which the calibration logs and treats as not measured.

Notice that the future's margin is within half a percent of 167,109.41, the figure most brokers gave.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/indmoney/IndmoneyMarginCalculator/example_2_reading_recorded_answers.py
"""

from unified_broker_interface.utilities.margin_calculators.base import (
    MarginCalculatorError,
)
from unified_broker_interface.utilities.margin_calculators.indmoney import (
    IndmoneyMarginCalculator,
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
    """Reads INDmoney's recorded answers.

    Attributes:
        calculator (IndmoneyMarginCalculator): The calculator, with stand-in credentials.
        order_answer (dict): What it answered for the NIFTY future.
    """

    def __init__(self):
        """Builds the calculator and holds the recorded answers.

        Returns:
            None: This method returns nothing.
        """
        self.calculator = IndmoneyMarginCalculator(STAND_IN_LOGIN, STAND_IN_SETTINGS)
        self.order_answer = {
            "status": "success",
            "data": {
                "total_margin": 167789.13,
                "span_margin": 138112.73,
                "ha": False,
                "hedge_benefit": 0,
                "exposure_margin": 29676.4,
                "available_balance": 0,
                "var_margin": 0,
                "insufficient_balance": 0,
                "delivery_margin": 0,
                "brokerage": 0,
                "charges": {
                    "stt": 0,
                    "exchange_charges": 0,
                    "stamp_duty": 0,
                    "sebi_turn_over_charges": 1.47,
                    "brokerage": 5,
                    "gst": 1.16,
                    "IPFTCharges": 0,
                    "total_charges": 7.63
                }
            }
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
