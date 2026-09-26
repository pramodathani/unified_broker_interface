"""Offline checks of the rule that decides whether a currency or commodity contract's size is trusted.

The rules in `stock_brokers/instruments/mapping/utilities/contract_sizes.py`, the per-contract decision and the upgrade of an MCX single-source contract by its confirmed siblings, are run on made-up source figures, so no database, Redis or network is used.

Typical usage:

    python -m test_runs.contract_sizes
"""

import decimal
import sys

from stock_brokers.instruments.mapping.utilities.contract_sizes import (
    ContractSizeDecision,
)


class ContractSizeDecisionSuite:
    """Runs every check of the contract size rule and reports how many passed.

    Attributes:
        decision (ContractSizeDecision): The rule under test.
        passed (int): How many checks passed.
        failed (list): The names of the checks that failed.
    """

    def __init__(self):
        """Builds the suite.

        Returns:
            None: This method returns nothing.
        """
        self.decision = ContractSizeDecision()
        self.passed = 0
        self.failed = []

    def figures(self, **sizes):
        """Builds source figures from keyword arguments.

        Args:
            **sizes (str): Source names to sizes written as text.

        Returns:
            dict: Source names to sizes as decimals.
        """
        figures = {}
        for source_name, size in sizes.items():
            figures[source_name] = decimal.Decimal(size)
        return figures

    def check(self, name, segment, figures, expected):
        """Runs the rule on one case and records whether it gave the expected decision.

        Args:
            name (str): The check's name.
            segment (str): The contract's segment.
            figures (dict): The source figures.
            expected (tuple): The expected `(units_per_lot, status, tradeable)`.

        Returns:
            None: This method returns nothing.
        """
        actual = self.decision.decide(segment, figures)
        if actual == expected:
            self.passed = self.passed + 1
            print(f'ok      {name}: {actual}')
        else:
            self.failed.append(name)
            print(f'FAILED  {name}: expected {expected}, got {actual}')

    def check_siblings(self, name, segment, decided, sibling_sizes, expected):
        """Runs the sibling rule on one decision and records whether it gave the expected status.

        Args:
            name (str): The check's name.
            segment (str): The contract's segment.
            decided (tuple): The `(units_per_lot, status, tradeable)` the first rule gave.
            sibling_sizes (set): The confirmed sizes of the same underlying in the segment.
            expected (tuple): The expected `(status, tradeable)`.

        Returns:
            None: This method returns nothing.
        """
        units_per_lot, status, tradeable = decided
        actual = self.decision.settle_by_siblings(
            segment,
            units_per_lot,
            status,
            tradeable,
            sibling_sizes,
        )
        if actual == expected:
            self.passed = self.passed + 1
            print(f'ok      {name}: {actual}')
        else:
            self.failed.append(name)
            print(f'FAILED  {name}: expected {expected}, got {actual}')

    def run(self):
        """Runs every check.

        Returns:
            int: The exit code: 0 when every check passed, 1 otherwise.
        """
        hundred = decimal.Decimal('100')
        thousand = decimal.Decimal('1000')
        self.check(
            'three agreeing MCX sources are confirmed',
            'mcx_commodity_futures',
            self.figures(wisdom='100', kotak='100.0', groww='1E+2'),
            (hundred, 'confirmed', True),
        )
        self.check(
            'two agreeing NSE currency sources are confirmed',
            'nse_currency_options',
            self.figures(kotak='1000', shoonya='1000'),
            (thousand, 'confirmed', True),
        )
        self.check(
            'one disagreeing source makes a conflict, even against two',
            'nse_currency_options',
            self.figures(kotak='1000', shoonya='1000', stoxkart='2000'),
            (None, 'conflict', False),
        )
        self.check(
            'a single MCX source is not tradeable',
            'mcx_commodity_options',
            self.figures(kotak='100'),
            (hundred, 'single_source', False),
        )
        self.check(
            'a single NSE commodity source is not tradeable',
            'nse_commodity_futures',
            self.figures(wisdom='1'),
            (decimal.Decimal('1'), 'single_source', False),
        )
        self.check(
            'a single BSE currency source is tradeable',
            'bse_currency_futures',
            self.figures(stoxkart='1000'),
            (thousand, 'single_source', True),
        )
        self.check(
            'a single NCDEX source is tradeable',
            'ncdex_commodity_options',
            self.figures(stoxkart='3'),
            (decimal.Decimal('3'), 'single_source', True),
        )
        self.check(
            'no source is not tradeable',
            'mcx_commodity_futures',
            {},
            (None, 'no_source', False),
        )
        natural_gas = decimal.Decimal('1250')
        self.check_siblings(
            'a single MCX source matching every confirmed sibling is sibling confirmed',
            'mcx_commodity_options',
            (natural_gas, 'single_source', False),
            {
                decimal.Decimal('1250.0'),
            },
            ('sibling_confirmed', True),
        )
        self.check_siblings(
            'a single MCX source is not upgraded when the siblings have two sizes',
            'mcx_commodity_index_options',
            (decimal.Decimal('15'), 'single_source', False),
            {
                decimal.Decimal('15'),
                decimal.Decimal('30'),
            },
            ('single_source', False),
        )
        self.check_siblings(
            'a single MCX source that disagrees with its siblings is not upgraded',
            'mcx_commodity_options',
            (natural_gas, 'single_source', False),
            {
                decimal.Decimal('250'),
            },
            ('single_source', False),
        )
        self.check_siblings(
            'a single MCX source with no confirmed sibling is not upgraded',
            'mcx_commodity_options',
            (natural_gas, 'single_source', False),
            set(),
            ('single_source', False),
        )
        self.check_siblings(
            'a single NSE commodity source is not upgraded outside MCX',
            'nse_commodity_futures',
            (decimal.Decimal('1'), 'single_source', False),
            {
                decimal.Decimal('1'),
            },
            ('single_source', False),
        )
        self.check_siblings(
            'a conflict is never upgraded',
            'mcx_commodity_options',
            (None, 'conflict', False),
            {
                None,
            },
            ('conflict', False),
        )
        total = self.passed + len(self.failed)
        print(f'{self.passed}/{total} checks passed.')
        if self.failed:
            return 1
        return 0


if __name__ == '__main__':
    sys.exit(ContractSizeDecisionSuite().run())
