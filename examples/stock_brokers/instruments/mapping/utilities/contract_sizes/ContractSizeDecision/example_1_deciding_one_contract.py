"""Decides the contract size of five contracts from what each source says about them.

`decide` looks only at the figures it is given. Two or more sources that agree make a contract `confirmed`; one source makes it `single_source`, which is tradeable only on BSE currencies and NCDEX, where Stoxkart is the only broker listing them; any disagreement, including one source giving two sizes for the same contract, makes it a `conflict`; and no figure at all makes it `no_source`.

The figures are made up but follow real contract sizes: 100 units for MCX GOLD, 1000 for a USDINR contract and 5 tonnes for an NCDEX DHANIYA future. `market` is printed beside each decision because the tradeable flag of a single-source contract depends on it. No database is needed.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/contract_sizes/ContractSizeDecision/example_1_deciding_one_contract.py
"""

import decimal

from stock_brokers.instruments.mapping.utilities.contract_sizes import (
    ContractSizeDecision,
)


class DecidingOneContractExample:
    """Runs the decision rule over five contracts and prints each answer.

    Attributes:
        decision (ContractSizeDecision): The rule being shown.
        cases (list): Tuples of a label, a segment, the figures and the contradicting sources.
    """

    def __init__(self):
        """Builds the rule and the five cases.

        Returns:
            None: This method returns nothing.
        """
        self.decision = ContractSizeDecision()
        self.cases = [
            (
                'MCX GOLD, three sources agree',
                'mcx_commodity_futures',
                {
                    'wisdom_capital_multiplier': decimal.Decimal('100'),
                    'kotak_contract_size': decimal.Decimal('100'),
                    'groww_lot_size': decimal.Decimal('100'),
                },
                None,
            ),
            (
                'NSE USDINR, one source disagrees',
                'nse_currency_options',
                {
                    'kotak_contract_size': decimal.Decimal('1000'),
                    'shoonya_lot_size_times_multiplier': decimal.Decimal('1000'),
                    'stoxkart_lot_size': decimal.Decimal('2000'),
                },
                None,
            ),
            (
                'NSE USDINR, Stoxkart lists it twice',
                'nse_currency_options',
                {
                    'kotak_contract_size': decimal.Decimal('1000'),
                    'shoonya_lot_size_times_multiplier': decimal.Decimal('1000'),
                },
                {
                    'stoxkart_lot_size',
                },
            ),
            (
                'NCDEX DHANIYA, Stoxkart only',
                'ncdex_commodity_futures',
                {
                    'stoxkart_lot_size': decimal.Decimal('5'),
                },
                None,
            ),
            (
                'MCX ZINC, no source',
                'mcx_commodity_futures',
                {},
                None,
            ),
        ]

    def run(self):
        """Prints the market and the decision for each case.

        Returns:
            None: This method returns nothing.
        """
        for label, segment, figures, contradicting_sources in self.cases:
            market = self.decision.market(segment)
            units_per_lot, status, tradeable = self.decision.decide(
                segment,
                figures,
                contradicting_sources,
            )
            print(f'{label}')
            print(f'  market {market}: size {units_per_lot}, {status}, tradeable {tradeable}')


if __name__ == '__main__':
    DecidingOneContractExample().run()
