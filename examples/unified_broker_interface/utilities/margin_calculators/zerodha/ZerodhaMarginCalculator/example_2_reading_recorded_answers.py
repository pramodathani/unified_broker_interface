"""Reads the margin out of answers Zerodha's calculator gave on 2026-09-30, and shows the error for an answer without one.

These are the real answers for one lot of NIFTY October futures sold at 22,833.70 and for a NIFTY iron condor (23200 call and 22400 put bought, 23000 call and 22600 put sold, one lot each), with account identifiers removed. `read_order_margin` and `read_basket_margin` pick out the one figure the calibration compares; an answer that lacks it raises `MarginCalculatorError`, which the calibration logs and treats as not measured.

Notice that the future's margin is within half a percent of 167,109.41, the figure most brokers gave.

Run it from the project root:

    python examples/unified_broker_interface/utilities/margin_calculators/zerodha/ZerodhaMarginCalculator/example_2_reading_recorded_answers.py
"""

from unified_broker_interface.utilities.margin_calculators.base import (
    MarginCalculatorError,
)
from unified_broker_interface.utilities.margin_calculators.zerodha import (
    ZerodhaMarginCalculator,
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
    """Reads Zerodha's recorded answers.

    Attributes:
        calculator (ZerodhaMarginCalculator): The calculator, with stand-in credentials.
        order_answer (dict): What it answered for the NIFTY future.
        basket_answer (dict): What it answered for the NIFTY iron condor, bought legs first.
    """

    def __init__(self):
        """Builds the calculator and holds the recorded answers.

        Returns:
            None: This method returns nothing.
        """
        self.calculator = ZerodhaMarginCalculator(STAND_IN_LOGIN, STAND_IN_SETTINGS)
        self.order_answer = {
            "status": "success",
            "data": [
                {
                    "type": "equity",
                    "tradingsymbol": "NIFTY26OCTFUT",
                    "exchange": "NFO",
                    "span": 137425.59999999998,
                    "exposure": 29683.81,
                    "option_premium": 0,
                    "additional": 0,
                    "bo": 0,
                    "cash": 0,
                    "var": 0,
                    "mtf": 0,
                    "pnl": {
                        "realised": 0,
                        "unrealised": 0
                    },
                    "leverage": 1,
                    "charges": {
                        "transaction_tax": 742.09525,
                        "transaction_tax_type": "stt",
                        "exchange_turnover_charge": 27.16068615,
                        "sebi_turnover_charge": 1.4841905,
                        "brokerage": 20,
                        "stamp_duty": 0,
                        "gst": {
                            "igst": 8.756077796999998,
                            "cgst": 0,
                            "sgst": 0,
                            "total": 8.756077796999998
                        },
                        "total": 799.496204447
                    },
                    "total": 167109.40999999997
                }
            ]
        }
        self.basket_answer = {
            "status": "success",
            "data": {
                "initial": {
                    "type": "",
                    "tradingsymbol": "",
                    "exchange": "",
                    "charges": {
                        "transaction_tax": 0,
                        "transaction_tax_type": "",
                        "exchange_turnover_charge": 0,
                        "sebi_turnover_charge": 0,
                        "brokerage": 0,
                        "stamp_duty": 0,
                        "gst": {
                            "igst": 0,
                            "cgst": 0,
                            "sgst": 0,
                            "total": 0
                        },
                        "total": 0
                    },
                    "total": 75476.37
                },
                "final": {
                    "type": "",
                    "tradingsymbol": "",
                    "exchange": "",
                    "charges": {
                        "transaction_tax": 0,
                        "transaction_tax_type": "",
                        "exchange_turnover_charge": 0,
                        "sebi_turnover_charge": 0,
                        "brokerage": 0,
                        "stamp_duty": 0,
                        "gst": {
                            "igst": 0,
                            "cgst": 0,
                            "sgst": 0,
                            "total": 0
                        },
                        "total": 0
                    },
                    "total": 66753.37
                },
                "orders": [
                    {
                        "type": "equity",
                        "tradingsymbol": "NIFTY26O0623200CE",
                        "exchange": "NFO",
                        "charges": {
                            "transaction_tax": 0,
                            "transaction_tax_type": "stt",
                            "exchange_turnover_charge": 0.4387955,
                            "sebi_turnover_charge": 0.001235,
                            "brokerage": 20,
                            "stamp_duty": 0,
                            "gst": {
                                "igst": 3.6792054899999997,
                                "cgst": 0,
                                "sgst": 0,
                                "total": 3.6792054899999997
                            },
                            "total": 24.119235990000004
                        },
                        "total": 1235
                    }
                ],
                "charges": {
                    "transaction_tax": 0,
                    "transaction_tax_type": "",
                    "exchange_turnover_charge": 0,
                    "sebi_turnover_charge": 0.012362999999999999,
                    "brokerage": 80,
                    "stamp_duty": 0,
                    "gst": {
                        "igst": 0,
                        "cgst": 0,
                        "sgst": 0,
                        "total": 0
                    },
                    "total": 0
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
