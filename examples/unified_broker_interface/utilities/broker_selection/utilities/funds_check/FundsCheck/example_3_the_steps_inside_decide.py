"""Walks through the steps `decide` takes, one method at a time, for a crude oil future at Zerodha and Dhan.

`decide` joins the Lua script's reply with the orders, reads each broker's entry out of the funds document, works out each broker's surcharge, and compares the margin with the cash in the right money pool. This program calls each of those steps itself, with Zerodha's and Dhan's funds of 2026-09-30 and the crude oil price of that morning, so each can be seen on its own. `text` and `read_time` are the small readers the others use for Redis replies and funds times.

Notice that Zerodha keeps commodity money apart and had none, so its free cash for this order is zero, while Dhan has one pool and offers all of it. Stoxkart, which has no measured surcharge, would be charged the 1.15 default.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/funds_check/FundsCheck/example_3_the_steps_inside_decide.py
"""

import datetime
import decimal
import json
import logging

from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCosts,
    BrokerCostTable,
)
from unified_broker_interface.utilities.broker_selection.utilities.funds_check import (
    POOL_NAMES,
    FundsCheck,
)
from unified_broker_interface.utilities.broker_selection.utilities.margin_rate_table import (
    MarginRate,
    MarginRateTable,
)
from unified_broker_interface.utilities.broker_selection.utilities.order_legs import (
    OrderLegs,
)

CRUDE_IDENTITY = {
    'segment': 'mcx_commodity_futures',
    'shape': 'future',
    'underlying_symbol': 'CRUDEOIL',
    'expiry_date': '2026-10-19',
    'strike_price': None,
    'option_type': None,
}


class StandInOrder:
    """A limit order to buy one lot of crude oil, 100 barrels.

    Attributes:
        transaction_type (str): `BUY`.
        product (str): `NRML`.
        quantity (int): 100.
        price (decimal.Decimal): The limit price.
        trigger_price (None): No trigger.
        dry_run (bool): False.
    """

    def __init__(self):
        """Builds the order.

        Returns:
            None: This method returns nothing.
        """
        self.transaction_type = 'BUY'
        self.product = 'NRML'
        self.quantity = 100
        self.price = decimal.Decimal('8618')
        self.trigger_price = None
        self.dry_run = False


class TheStepsInsideDecideExample:
    """Calls each step of the funds check in turn.

    Attributes:
        check (FundsCheck): The check.
        funds_text (bytes): The funds document as Redis returns it without decoding.
    """

    def __init__(self):
        """Builds the tables, the check and the funds document.

        Returns:
            None: This method returns nothing.
        """
        logger = logging.getLogger('example')
        fees = {
            'delivery': decimal.Decimal(0),
            'fno': decimal.Decimal(20),
            'intraday': decimal.Decimal(20),
        }
        commodity_multiplier = {
            'commodity': decimal.Decimal('1.000'),
        }
        rows = {
            'dhan': BrokerCosts('dhan', 9, 480, 7000, None, fees, commodity_multiplier, True),
            'zerodha': BrokerCosts('zerodha', 9, 375, None, 4500, fees, commodity_multiplier, True),
        }
        margin_rates = [
            MarginRate('mcx_commodity_futures', 'CRUDEOIL', decimal.Decimal('0.302'), decimal.Decimal('0.0125')),
        ]
        self.check = FundsCheck(
            BrokerCostTable(logger, rows),
            MarginRateTable(logger, margin_rates),
            True,
            0.05,
            1.15,
            5,
            2,
        )
        document = {
            'brokers': [
                {
                    'broker': 'dhan',
                    'status': 'ok',
                    'as_of': '2026-09-30 10:39:59.500000',
                    'available_balance': 9891.75,
                    'pools': {},
                },
                {
                    'broker': 'zerodha',
                    'status': 'ok',
                    'as_of': '2026-09-30 10:39:59.500000',
                    'available_balance': 56040.0,
                    'pools': {
                        'equity': 56040.0,
                        'commodity': 0.0,
                    },
                },
            ],
        }
        self.funds_text = json.dumps(document).encode()

    def run(self):
        """Prints each step's result.

        Returns:
            None: This method returns nothing.
        """
        legs = OrderLegs([
            ('crude-2026-10-19', StandInOrder()),
        ])
        script_reply = [
            json.dumps(CRUDE_IDENTITY).encode(),
            b'8618',
            b'',
        ]
        priced_legs = self.check.priced_legs(legs, script_reply)
        leg = priced_legs[0]
        print(f'Priced leg: {leg.shape()} in {leg.segment()} at {leg.last_price}, market {leg.market_category()}')
        margin = self.check.margin_estimate.required(priced_legs, False)
        print(f'Exchange margin: {margin:,.2f}')
        print(f'text of b"8618": {self.check.text(b"8618")!r}, of None: {self.check.text(None)!r}')
        read_at = self.check.read_time('2026-09-30 10:39:59.500000')
        print(f'read_time: {read_at}, of nonsense: {self.check.read_time("yesterday")}')
        funds_by_broker = self.check.funds_by_broker(self.funds_text)
        print(f'Brokers in the funds document: {sorted(funds_by_broker)}')
        pool_names = POOL_NAMES[leg.market_category()]
        now = datetime.datetime(2026, 9, 30, 10, 40, 0)
        for broker_name in ['zerodha', 'dhan', 'stoxkart']:
            costs = self.check.cost_table.costs(broker_name)
            multiplier = self.check.multiplier(costs, priced_legs)
            free_cash, problem = self.check.available(broker_name, funds_by_broker.get(broker_name), pool_names, now)
            print(f'{broker_name}: multiplier {multiplier}, free cash {free_cash}, problem {problem}')


if __name__ == '__main__':
    TheStepsInsideDecideExample().run()
