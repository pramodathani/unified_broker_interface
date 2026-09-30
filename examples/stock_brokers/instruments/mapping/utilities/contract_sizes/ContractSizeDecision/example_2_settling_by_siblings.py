"""Upgrades a newly listed MCX contract that only one broker lists yet, by checking its already confirmed siblings.

Some brokers add a new far-month expiry later than others, so on MCX a new NATURALGAS option can have a single source for a few days. `decide` calls it `single_source` and untradeable. `settle_by_siblings` then looks at the sizes of the confirmed contracts of the same underlying in the same segment: when they all have one size and it is the single source's figure, the contract becomes `sibling_confirmed` and tradeable.

The program runs four such checks. The first is upgraded. The second is not, because the siblings come in two sizes, as happens after the exchange revises a lot. The third is not, because the single figure disagrees with the siblings. The fourth is on NSE commodities, where the sibling rule does not apply at all. The figures are made up; no database is needed.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/contract_sizes/ContractSizeDecision/example_2_settling_by_siblings.py
"""

import decimal

from stock_brokers.instruments.mapping.utilities.contract_sizes import (
    ContractSizeDecision,
)


class SettlingBySiblingsExample:
    """Decides four single-source contracts and then settles each against its siblings.

    Attributes:
        decision (ContractSizeDecision): The rule being shown.
        cases (list): Tuples of a label, a segment, the single source's figure and the siblings' confirmed sizes.
    """

    def __init__(self):
        """Builds the rule and the four cases.

        Returns:
            None: This method returns nothing.
        """
        self.decision = ContractSizeDecision()
        self.cases = [
            (
                'MCX NATURALGAS far-month option',
                'mcx_commodity_options',
                decimal.Decimal('1250'),
                {
                    decimal.Decimal('1250'),
                },
            ),
            (
                'MCX index option after a lot revision',
                'mcx_commodity_index_options',
                decimal.Decimal('15'),
                {
                    decimal.Decimal('15'),
                    decimal.Decimal('30'),
                },
            ),
            (
                'MCX option disagreeing with its siblings',
                'mcx_commodity_options',
                decimal.Decimal('1250'),
                {
                    decimal.Decimal('250'),
                },
            ),
            (
                'NSE commodity future',
                'nse_commodity_futures',
                decimal.Decimal('1'),
                {
                    decimal.Decimal('1'),
                },
            ),
        ]

    def run(self):
        """Prints the first decision and the settled status for each case.

        Returns:
            None: This method returns nothing.
        """
        print(f'Markets where one source is enough: {ContractSizeDecision.SINGLE_SOURCE_MARKETS}')
        print(f'Markets where siblings can confirm: {ContractSizeDecision.SIBLING_MARKETS}')
        for label, segment, figure, sibling_sizes in self.cases:
            units_per_lot, status, tradeable = self.decision.decide(
                segment,
                {
                    'kotak_contract_size': figure,
                },
            )
            settled_status, settled_tradeable = self.decision.settle_by_siblings(
                segment,
                units_per_lot,
                status,
                tradeable,
                sibling_sizes,
            )
            print(f'{label}: {status} {tradeable} -> {settled_status} {settled_tradeable}')


if __name__ == '__main__':
    SettlingBySiblingsExample().run()
