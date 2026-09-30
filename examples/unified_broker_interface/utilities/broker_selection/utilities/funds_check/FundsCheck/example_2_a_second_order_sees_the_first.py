"""Sends two identical delivery buys to Zerodha one after the other and shows the second one seeing the first.

When the placement settles on a broker it tells the selector, and the funds check reserves the order's margin there with `reserve_chosen`. The next order is then compared with the broker's free cash less that reservation, even though the funds document, read every half second, does not show the first order yet. A dry run chooses a broker but sends nothing, so it reserves nothing. This program uses Zerodha's free cash of 2026-09-30, 56,040, and buys 50 INFY shares at 1,017.70 each time.

Notice that the dry run and the first order both fit, because the dry run held nothing back, while the second identical order is passed over: it needs about 53,430 and only about 2,610 is left once the first order's reservation is taken off.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/funds_check/FundsCheck/example_2_a_second_order_sees_the_first.py
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
    FundsCheck,
)
from unified_broker_interface.utilities.broker_selection.utilities.margin_rate_table import (
    MarginRate,
    MarginRateTable,
)

INFY_IDENTITY = {
    'segment': 'nse_equities',
    'shape': 'security',
    'underlying_symbol': None,
    'expiry_date': None,
    'strike_price': None,
    'option_type': None,
}


class StandInOrder:
    """A delivery buy of 50 INFY shares.

    Attributes:
        transaction_type (str): `BUY`.
        product (str): `CNC`.
        quantity (int): 50.
        price (decimal.Decimal): The limit price.
        trigger_price (None): No trigger.
        dry_run (bool): Whether the order is a dry run.
    """

    def __init__(self, dry_run):
        """Builds the order.

        Args:
            dry_run (bool): Whether the order is a dry run.

        Returns:
            None: This method returns nothing.
        """
        self.transaction_type = 'BUY'
        self.product = 'CNC'
        self.quantity = 50
        self.price = decimal.Decimal('1017.7')
        self.trigger_price = None
        self.dry_run = dry_run


class DiscardingPipeline:
    """A pipeline that accepts commands and keeps none of them.

    Attributes:
        count (int): How many commands were queued.
    """

    def __init__(self):
        """Builds the pipeline.

        Returns:
            None: This method returns nothing.
        """
        self.count = 0

    def get(self, key):
        """Accepts a `GET`.

        Args:
            key (str): The key.

        Returns:
            DiscardingPipeline: This pipeline.
        """
        del key
        self.count = self.count + 1
        return self

    def eval(self, script, key_count, *keys_and_arguments):
        """Accepts an `EVAL`.

        Args:
            script (str): The Lua script.
            key_count (int): How many of the values are keys.
            *keys_and_arguments (str): The keys, then the arguments.

        Returns:
            DiscardingPipeline: This pipeline.
        """
        del script
        del key_count
        del keys_and_arguments
        self.count = self.count + 1
        return self


class ASecondOrderSeesTheFirstExample:
    """Runs the check three times at Zerodha, reserving after each order that is not a dry run.

    Attributes:
        check (FundsCheck): The check.
        now (datetime.datetime): The moment the funds are judged at.
        funds_text (str): The funds document, which does not change during the program.
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
        rows = {
            'zerodha': BrokerCosts('zerodha', 9, 375, None, 4500, fees, {}, True),
        }
        margin_rates = [
            MarginRate('nse_equities', '', decimal.Decimal('0.20'), decimal.Decimal('0')),
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
        self.now = datetime.datetime.now()
        read_at = self.now - datetime.timedelta(milliseconds=300)
        self.funds_text = json.dumps({
            'brokers': [
                {
                    'broker': 'zerodha',
                    'status': 'ok',
                    'as_of': read_at.strftime('%Y-%m-%d %H:%M:%S.%f'),
                    'available_balance': 56040.0,
                    'pools': {
                        'equity': 56040.0,
                        'commodity': 0.0,
                    },
                },
            ],
        })

    def one_order(self, description, dry_run):
        """Checks one order at Zerodha, prints the verdict, and reserves its margin when it is chosen.

        Args:
            description (str): What the order is, for the output.
            dry_run (bool): Whether the order is a dry run.

        Returns:
            None: This method returns nothing.
        """
        order = StandInOrder(dry_run)
        self.check.queue_redis_commands(DiscardingPipeline(), order, 'infy')
        script_reply = [
            json.dumps(INFY_IDENTITY),
            '1017.7',
            '',
        ]
        self.check.decide([self.funds_text, script_reply], ['zerodha'], self.now)
        reason = self.check.reason('zerodha')
        if reason is None:
            self.check.reserve_chosen('zerodha')
            print(f'{description}: goes to Zerodha')
        else:
            print(f'{description}: Zerodha passed over, {reason}')

    def run(self):
        """Checks a dry run, a first order and a second order.

        Returns:
            None: This method returns nothing.
        """
        self.one_order('Dry run', True)
        self.one_order('First order', False)
        self.one_order('Second order', False)


if __name__ == '__main__':
    ASecondOrderSeesTheFirstExample().run()
