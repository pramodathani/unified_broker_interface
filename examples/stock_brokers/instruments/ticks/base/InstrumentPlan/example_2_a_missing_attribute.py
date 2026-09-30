"""Shows that a plan must be given every attribute, and cannot take one it does not declare.

`InstrumentPlan` declares its attributes in `__slots__` and its constructor reads each of them from the keyword arguments by name. That is deliberate: a plan is built once per token and read on every tick, so a plan missing a field would fail on the hot path, far from the mistake. Leaving one out fails at construction instead, with a `KeyError` naming the missing attribute.

Because of `__slots__`, a plan also refuses an attribute that is not declared, which catches a misspelt name. This program builds an equity plan without `identity_json` and catches the error, then builds a complete one and tries to set a misspelt attribute on it. It needs no data store or broker.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/base/InstrumentPlan/example_2_a_missing_attribute.py
"""

from stock_brokers.instruments.ticks import base
from stock_brokers.instruments.ticks.base import (
    InstrumentPlan,
)
from stock_brokers.instruments.ticks.utilities import sessions


class MissingAttributeExample:
    """Builds a plan without one attribute, then a complete one, and shows both refusals.

    Attributes:
        values (dict): The attributes of an NSE equity plan, without `identity_json`.
    """

    def __init__(self):
        """Prepares the attributes of a plan for RELIANCE on NSE, leaving one out.

        Returns:
            None: This method returns nothing.
        """
        multipliers = {}
        for field in base.QUANTITY_FIELDS:
            multipliers[field] = 1
        self.values = {
            'instrument_id': '11111111-1111-5111-8111-000000000102',
            'broker': 'zerodha',
            'broker_token': '738561',
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
            'session': sessions.session_for('nse_equities'),
            'lot_size': 1,
            'multipliers': multipliers,
            'price_decimals': 2,
            'negative_prices': False,
            'close_policy': base.CLOSE_ALWAYS,
            'has_open_interest': False,
            'trusts_last_trade_time': True,
            'trusts_exchange_time': True,
        }

    def run(self):
        """Prints the two refusals and the plan that was built.

        Returns:
            None: This method returns nothing.
        """
        try:
            InstrumentPlan(**self.values)
        except KeyError as error:
            print(f'Refused, missing attribute: {error}')
        self.values['identity_json'] = '"instrument_id":"11111111-1111-5111-8111-000000000102"'
        plan = InstrumentPlan(**self.values)
        print(f'Built a plan for {plan.segment} with lot size {plan.lot_size} and session {plan.session}')
        try:
            plan.lotsize = 5
        except AttributeError as error:
            print(f'Refused, undeclared attribute: {error}')


if __name__ == '__main__':
    MissingAttributeExample().run()
