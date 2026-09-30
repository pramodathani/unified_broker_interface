"""Offline checks of every broker's margin calculator against the requests and answers recorded from the live brokers.

On 2026-09-30 at about 10:40 IST every broker's margin calculator was sent one lot of NIFTY October futures sold and a NIFTY iron condor, and every request in `test_runs/fixtures/margin_calculators.json` is one the broker accepted, with account identifiers replaced by stand-ins. This suite builds the same orders through each calculator and checks that the request matches, number for number, and that each recorded answer is read as the right margin. A change to a calculator that would send something the broker has not accepted fails here, without any network, credentials or Redis.

Typical usage:

    python -m test_runs.margin_calculators
"""

import decimal
import json
import logging
import pathlib
import sys
import urllib.parse

from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.margin_calculators.base import (
    MarginCalculatorError,
)
from unified_broker_interface.utilities.margin_calculators.utilities.broker_measurement import (
    BrokerMeasurement,
)
from unified_broker_interface.utilities.margin_calculators.utilities.margin_calibration import (
    MarginCalibration,
)
from unified_broker_interface.utilities.margin_calculators.utilities.reference_leg import (
    ReferenceLeg,
)
from unified_broker_interface.utilities.margin_calculators.utilities.registry import (
    MARGIN_CALCULATOR_CLASSES,
)
from unified_broker_interface.utilities.margin_calculators.wisdom_capital import (
    WisdomCapitalMarginCalculator,
)

FIXTURE = pathlib.Path(__file__).parent / 'fixtures' / 'margin_calculators.json'

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

EXPECTED_ORDER_MARGINS = {
    'zerodha': '167109.40999999997',
    'dhan': '167109.4',
    'fyers': '167171.41',
    'groww': '167105.13',
    'indmoney': '167789.13',
    'kotak': '167151.411000',
    'flattrade': '185671.65',
    'shoonya': '176246.49',
    'wisdom_capital': '183820.35099999997',
}

EXPECTED_BASKET_MARGINS = {
    'zerodha': '66753.37',
    'dhan': '75923.77',
    'fyers': '187749.87',
    'groww': '75525.90',
    'flattrade': '79724.16',
    'shoonya': '75406.56',
    'wisdom_capital': '82847.42700000001',
}


class MarginCalculatorSuite:
    """Runs every check and reports how many passed.

    Attributes:
        fixture (dict): The recorded requests and answers, by broker, and the instruments they were for.
        passed (int): How many checks passed.
        failed (list): The names of the checks that failed.
    """

    def __init__(self):
        """Reads the fixture.

        Returns:
            None: This method returns nothing.
        """
        self.fixture = json.loads(FIXTURE.read_text())
        self.passed = 0
        self.failed = []

    def check(self, name, actual, expected):
        """Compares one value with what it should be, and prints the difference when they differ.

        Args:
            name (str): What is being checked.
            actual (object): The value produced.
            expected (object): The value it should be.

        Returns:
            None: This method returns nothing.
        """
        if actual == expected:
            self.passed = self.passed + 1
            return
        self.failed.append(name)
        print(f'FAILED  {name}')
        print(f'  expected: {expected!r}')
        print(f'  actual:   {actual!r}')

    def normalised(self, value):
        """A request body with every number, and every string that is a number, turned into one normalised decimal, so `19.0`, `19.00` and `"19"` compare equal.

        Args:
            value (object): The body or a part of it.

        Returns:
            object: The same structure with numbers normalised.
        """
        if isinstance(value, dict):
            normalised = {}
            for key, item in value.items():
                normalised[key] = self.normalised(item)
            return normalised
        if isinstance(value, list):
            items = []
            for item in value:
                items.append(self.normalised(item))
            return items
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, (int, float)):
            return decimal.Decimal(str(value)).normalize()
        if isinstance(value, str):
            try:
                return decimal.Decimal(value).normalize()
            except decimal.InvalidOperation:
                return value
        return value

    def leg(self, name, transaction_type):
        """One recorded instrument as a reference leg of one lot.

        Args:
            name (str): The instrument's name in the fixture, such as `NIFTYFUT`.
            transaction_type (str): `BUY` or `SELL`.

        Returns:
            ReferenceLeg: The leg.
        """
        recorded = self.fixture['instruments'][name]
        identity = {
            'segment': recorded['segment'],
            'shape': recorded['shape'],
        }
        instrument = Instrument(recorded['instrument_id'], identity, recorded['handles'])
        return ReferenceLeg(name, instrument, transaction_type, 'NRML', 65, decimal.Decimal(recorded['price']))

    def condor(self):
        """The iron condor as it was sent, bought legs first.

        Returns:
            list: The four legs.
        """
        return [
            self.leg('NIFTY23200CE', 'BUY'),
            self.leg('NIFTY22400PE', 'BUY'),
            self.leg('NIFTY23000CE', 'SELL'),
            self.leg('NIFTY22600PE', 'SELL'),
        ]

    def body(self, broker_request):
        """The fields a request carries, whichever way it encodes them.

        Args:
            broker_request (BrokerRequest): The request.

        Returns:
            object: The JSON body, or the decoded `jData` fields of a form body.
        """
        if broker_request.json_body is not None:
            return broker_request.json_body
        if isinstance(broker_request.data, dict):
            return json.loads(broker_request.data['jData'])
        form = urllib.parse.parse_qs(broker_request.data)
        return json.loads(form['jData'][0])

    def run(self):
        """Runs every check and prints how many passed.

        Returns:
            int: 0 when every check passed, 1 when any failed.
        """
        for calculator_class in MARGIN_CALCULATOR_CLASSES:
            self.requests_match_what_the_broker_accepted(calculator_class)
            self.recorded_answers_are_read(calculator_class)
        self.a_zero_margin_is_not_an_answer()
        self.the_calibration_finds_the_surcharges()
        self.fyers_is_not_counted_as_hedging()

        total = self.passed + len(self.failed)
        print(f'{total - len(self.failed)}/{total} checks passed.')
        if self.failed:
            return 1
        return 0

    def requests_match_what_the_broker_accepted(self, calculator_class):
        """The order and basket requests carry exactly the fields the live broker accepted.

        Args:
            calculator_class (type): The broker's calculator class.

        Returns:
            None: This method returns nothing.
        """
        broker_name = calculator_class.BROKER_NAME
        recorded = self.fixture[broker_name]
        calculator = calculator_class(STAND_IN_LOGIN, STAND_IN_SETTINGS)
        future = self.leg('NIFTYFUT', 'SELL')
        request = calculator.build_order_request(future)
        self.check(
            f'{broker_name} order request',
            self.normalised(self.body(request)),
            self.normalised(recorded['order_request']),
        )
        if 'basket_request' not in recorded:
            self.check(f'{broker_name} has no basket calculator', calculator.TAKES_BASKETS, False)
            return
        request = calculator.build_basket_request(self.condor())
        self.check(
            f'{broker_name} basket request',
            self.normalised(self.body(request)),
            self.normalised(recorded['basket_request']),
        )

    def recorded_answers_are_read(self, calculator_class):
        """Each recorded answer is read as the margin the broker gave.

        Args:
            calculator_class (type): The broker's calculator class.

        Returns:
            None: This method returns nothing.
        """
        broker_name = calculator_class.BROKER_NAME
        recorded = self.fixture[broker_name]
        calculator = calculator_class(STAND_IN_LOGIN, STAND_IN_SETTINGS)
        self.check(
            f'{broker_name} order answer',
            calculator.read_order_margin(recorded['order_answer']),
            decimal.Decimal(EXPECTED_ORDER_MARGINS[broker_name]),
        )
        if broker_name in EXPECTED_BASKET_MARGINS:
            self.check(
                f'{broker_name} basket answer',
                calculator.read_basket_margin(recorded['basket_answer']),
                decimal.Decimal(EXPECTED_BASKET_MARGINS[broker_name]),
            )

    def a_zero_margin_is_not_an_answer(self):
        """Wisdom Capital answered zero for crude oil; that must raise rather than be recorded as a margin.

        Returns:
            None: This method returns nothing.
        """
        calculator = WisdomCapitalMarginCalculator(STAND_IN_LOGIN, STAND_IN_SETTINGS)
        answer = {
            'result': {
                'brokerageDeatils': {
                    'IsValid': True,
                    'MarginRequired': 0,
                },
            },
        }
        raised = False
        try:
            calculator.read_order_margin(answer)
        except MarginCalculatorError:
            raised = True
        self.check('a zero margin raises', raised, True)

    def the_calibration_finds_the_surcharges(self):
        """From the recorded future answers, Flattrade, Shoonya and Wisdom Capital carry surcharges and the rest are at 1.

        Returns:
            None: This method returns nothing.
        """
        calibration = MarginCalibration(None, logging.getLogger('test_runs.margin_calculators'), [])
        measurements = []
        for broker_name, margin_text in EXPECTED_ORDER_MARGINS.items():
            measurement = BrokerMeasurement(broker_name)
            measurement.margins['fno'] = decimal.Decimal(margin_text)
            measurements.append(measurement)
        exchange = calibration.exchange_margins(measurements)
        multipliers = {}
        for measurement in measurements:
            multipliers[measurement.broker_name] = calibration.multipliers(measurement, exchange)['fno']
        self.check(
            'F&O multipliers',
            multipliers,
            {
                'zerodha': decimal.Decimal('1.000'),
                'dhan': decimal.Decimal('1.000'),
                'fyers': decimal.Decimal('1.000'),
                'groww': decimal.Decimal('1.000'),
                'indmoney': decimal.Decimal('1.004'),
                'kotak': decimal.Decimal('1.000'),
                'flattrade': decimal.Decimal('1.111'),
                'shoonya': decimal.Decimal('1.054'),
                'wisdom_capital': decimal.Decimal('1.100'),
            },
        )

    def fyers_is_not_counted_as_hedging(self):
        """Fyers' condor basket was 59% of its legs, which is not hedge benefit; Zerodha's 22% is.

        Returns:
            None: This method returns nothing.
        """
        fyers = BrokerMeasurement('fyers')
        fyers.basket_margin = decimal.Decimal('181158.47')
        fyers.legs_margin = decimal.Decimal('308000.12')
        zerodha = BrokerMeasurement('zerodha')
        zerodha.basket_margin = decimal.Decimal('66960.20')
        zerodha.legs_margin = decimal.Decimal('306010.77')
        self.check('Fyers gives no hedge benefit', fyers.gives_hedge_benefit(), False)
        self.check('Zerodha gives hedge benefit', zerodha.gives_hedge_benefit(), True)


if __name__ == '__main__':
    sys.exit(MarginCalculatorSuite().run())
