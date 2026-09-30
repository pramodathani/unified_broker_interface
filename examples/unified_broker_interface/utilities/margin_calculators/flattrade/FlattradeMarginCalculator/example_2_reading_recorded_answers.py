"""Reads the margin out of answers Flattrade's calculator gave on 2026-09-30, and shows the error for an answer without one.

These are the real answers for one lot of NIFTY October futures sold at 22,833.70 and for a NIFTY iron condor (23200 call and 22400 put bought, 23000 call and 22600 put sold, one lot each), with account identifiers removed. `read_order_margin` and `read_basket_margin` pick out the one figure the calibration compares; an answer that lacks it raises `MarginCalculatorError`, which the calibration logs and treats as not measured.

Notice that the future's margin is within half a percent of 167,109.41, the figure most brokers gave, except where this broker adds its own surcharge.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/flattrade/FlattradeMarginCalculator/example_2_reading_recorded_answers.py
"""

from unified_broker_interface.utilities.margin_calculators.base import (
    MarginCalculatorError,
)
from unified_broker_interface.utilities.margin_calculators.flattrade import (
    FlattradeMarginCalculator,
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
    """Reads Flattrade's recorded answers.

    Attributes:
        calculator (FlattradeMarginCalculator): The calculator, with stand-in credentials.
        order_answer (dict): What it answered for the NIFTY future.
        basket_answer (dict): What it answered for the NIFTY iron condor, bought legs first.
    """

    def __init__(self):
        """Builds the calculator and holds the recorded answers.

        Returns:
            None: This method returns nothing.
        """
        self.calculator = FlattradeMarginCalculator(STAND_IN_LOGIN, STAND_IN_SETTINGS)
        self.order_answer = {
            "request_time": "10:41:36 30-09-2026",
            "stat": "Ok",
            "cash": "12675.96",
            "marginused": "172995.69",
            "remarks": "Insufficient Balance",
            "marginusedprev": "0.00",
            "ordermargin": "185671.65"
        }
        self.basket_answer = {
            "request_time": "10:41:36 30-09-2026",
            "stat": "Ok",
            "marginused": "207953.01",
            "marginusedtrade": "79724.16",
            "marginusedprev": "0.00",
            "remarks": ""
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
