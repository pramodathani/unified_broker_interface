"""Reads the margin out of answers Wisdom Capital's calculator gave on 2026-09-30, and shows the error for an answer without one.

These are the real answers for one lot of NIFTY October futures sold at 22,833.70 and for a NIFTY iron condor (23200 call and 22400 put bought, 23000 call and 22600 put sold, one lot each), with account identifiers removed. `read_order_margin` and `read_basket_margin` pick out the one figure the calibration compares; an answer that lacks it raises `MarginCalculatorError`, which the calibration logs and treats as not measured.

Notice that the future's margin is within half a percent of 167,109.41, the figure most brokers gave, except where this broker adds its own surcharge.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/wisdom_capital/WisdomCapitalMarginCalculator/example_2_reading_recorded_answers.py
"""

from unified_broker_interface.utilities.margin_calculators.base import (
    MarginCalculatorError,
)
from unified_broker_interface.utilities.margin_calculators.wisdom_capital import (
    WisdomCapitalMarginCalculator,
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
    """Reads Wisdom Capital's recorded answers.

    Attributes:
        calculator (WisdomCapitalMarginCalculator): The calculator, with stand-in credentials.
        order_answer (dict): What it answered for the NIFTY future.
        basket_answer (dict): What it answered for the NIFTY iron condor, bought legs first.
    """

    def __init__(self):
        """Builds the calculator and holds the recorded answers.

        Returns:
            None: This method returns nothing.
        """
        self.calculator = WisdomCapitalMarginCalculator(STAND_IN_LOGIN, STAND_IN_SETTINGS)
        self.order_answer = {
            "type": "success",
            "code": "s-calculatemargin-0001",
            "description": "calculate Margin Data",
            "result": {
                "brokerageDeatils": {
                    "IsValid": True,
                    "MarginRequired": 183820.35099999997,
                    "MarginAvailable": 4915.8,
                    "MarginShortfall": 178904.55099999998,
                    "ErrorMessage": ""
                }
            }
        }
        self.basket_answer = {
            "type": "success",
            "code": "s-calculatemargin-0001",
            "description": "calculate Margin Data",
            "result": {
                "brokerageDeatils": {
                    "IsValid": True,
                    "MarginRequired": 82847.42700000001,
                    "MarginAvailable": 0,
                    "MarginShortfall": 82847.42700000001,
                    "ErrorMessage": ""
                }
            }
        }

    def run(self):
        """Prints the margins read, then the error for an empty answer.

        Returns:
            None: This method returns nothing.
        """
        print(f'NIFTY future sold: {self.calculator.read_order_margin(self.order_answer)}')
        print(f'Iron condor as a basket: {self.calculator.read_basket_margin(self.basket_answer)}')
        try:
            self.calculator.read_order_margin({})
        except MarginCalculatorError as error:
            print(f'An empty answer: {error}')


if __name__ == '__main__':
    ReadingRecordedAnswersExample().run()
