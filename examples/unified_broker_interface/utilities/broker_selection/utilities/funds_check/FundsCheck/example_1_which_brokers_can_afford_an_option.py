"""Decides which of the ten brokers can afford to buy one lot of a NIFTY call, with the balances they held on 2026-09-30.

`FundsCheck` queues three commands on the pipeline that already reads the instrument, a `GET` of `unified:portfolio:funds`, a Lua script that returns the leg's identity and prices, and a `GET` of `unified:portfolio:positions`, and then `decide` compares each broker's estimated margin with its free cash. This program answers the first two commands with scripted replies holding the real free cash each account had at about 10:40 that morning, and the margin multipliers the DDL seeds, so it needs nothing running. It leaves out the positions document, because a buy of a call nobody holds closes nothing.

Notice that the call costs 7,962.50, about 8,360 with the 5% cushion. Kotak, Shoonya and Wisdom Capital hold under 5,000 and are passed over. Stoxkart holds 9,256.67, which would be enough, but it has no margin calculator to measure its surcharge by, so it carries the 1.15 default and is passed over too.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/utilities/funds_check/FundsCheck/example_1_which_brokers_can_afford_an_option.py
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

FREE_CASH = {
    'dhan': 9891.75,
    'flattrade': 12675.96,
    'fyers': 9916.1,
    'groww': 9751.19,
    'indmoney': 9754.97,
    'kotak': 4954.19,
    'shoonya': 4950.3,
    'stoxkart': 9256.67,
    'wisdom_capital': 4915.8,
    'zerodha': 56040.0,
}

FNO_MULTIPLIERS = {
    'dhan': '1.000',
    'flattrade': '1.111',
    'fyers': '1.001',
    'groww': '1.000',
    'indmoney': '1.005',
    'kotak': '1.000',
    'shoonya': '1.055',
    'stoxkart': None,
    'wisdom_capital': '1.100',
    'zerodha': '1.000',
}


class StandInOrder:
    """A limit order to buy one lot.

    Attributes:
        transaction_type (str): `BUY`.
        product (str): `NRML`.
        quantity (int): 65.
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
        self.quantity = 65
        self.price = decimal.Decimal('122.5')
        self.trigger_price = None
        self.dry_run = False


class RecordingPipeline:
    """A pipeline that records the commands queued on it.

    Attributes:
        commands (list): The command names, in order.
    """

    def __init__(self):
        """Builds an empty pipeline.

        Returns:
            None: This method returns nothing.
        """
        self.commands = []

    def get(self, key):
        """Records a `GET`.

        Args:
            key (str): The key.

        Returns:
            RecordingPipeline: This pipeline.
        """
        self.commands.append(f'GET {key}')
        return self

    def eval(self, script, key_count, *keys_and_arguments):
        """Records an `EVAL`.

        Args:
            script (str): The Lua script.
            key_count (int): How many of the values are keys.
            *keys_and_arguments (str): The keys, then the arguments.

        Returns:
            RecordingPipeline: This pipeline.
        """
        del script
        keys = list(keys_and_arguments[:key_count])
        arguments = list(keys_and_arguments[key_count:])
        self.commands.append(f'EVAL with keys {keys} and arguments {arguments}')
        return self


class WhichBrokersCanAffordAnOptionExample:
    """Runs the check for one bought call across ten brokers.

    Attributes:
        check (FundsCheck): The check.
        now (datetime.datetime): The moment the funds are judged at.
    """

    def __init__(self):
        """Builds the tables and the check.

        Returns:
            None: This method returns nothing.
        """
        logger = logging.getLogger('example')
        rows = {}
        for broker_name, multiplier in FNO_MULTIPLIERS.items():
            multipliers = {
                'fno': None if multiplier is None else decimal.Decimal(multiplier),
            }
            fees = {
                'delivery': decimal.Decimal(0),
                'fno': decimal.Decimal(20),
                'intraday': decimal.Decimal(20),
            }
            rows[broker_name] = BrokerCosts(broker_name, 10, None, None, None, fees, multipliers, None)
        margin_rates = [
            MarginRate('nse_equity_index_options', 'NIFTY', decimal.Decimal('0.0926'), decimal.Decimal('0.02')),
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
        self.now = datetime.datetime(2026, 9, 30, 10, 40, 0)

    def funds_document(self):
        """The unified funds document with every broker read half a second ago.

        Returns:
            str: The document as JSON.
        """
        brokers = []
        for broker_name, free_cash in FREE_CASH.items():
            brokers.append({
                'broker': broker_name,
                'status': 'ok',
                'as_of': '2026-09-30 10:39:59.500000',
                'available_balance': free_cash,
                'pools': {},
            })
        return json.dumps({
            'brokers': brokers,
        })

    def run(self):
        """Queues the commands, answers them, and prints each broker's verdict.

        Returns:
            None: This method returns nothing.
        """
        pipeline = RecordingPipeline()
        queued = self.check.queue_redis_commands(pipeline, StandInOrder(), 'nifty-2026-10-06-22800-ce')
        print(f'Active: {self.check.is_active()}, commands queued: {queued}')
        for command in pipeline.commands:
            print(f'  {command}')
        identity = {
            'segment': 'nse_equity_index_options',
            'shape': 'option',
            'underlying_symbol': 'NIFTY',
            'expiry_date': '2026-10-06',
            'strike_price': '22800.0',
            'option_type': 'CE',
        }
        script_reply = [
            json.dumps(identity),
            '122.5',
            '22721.25',
        ]
        reasons = self.check.decide([self.funds_document(), script_reply], list(FREE_CASH), self.now)
        for broker_name in FREE_CASH:
            print(f'{broker_name}: {self.check.reason(broker_name) or "can afford it"}')
        print(f'{len(reasons)} brokers passed over')


if __name__ == '__main__':
    WhichBrokersCanAffordAnOptionExample().run()
