"""Reads the candidates of a three-stock basket into the order bodies the engine validates and sends.

A basket, a spread or a one-cancels-all group is made of several orders, each on its own instrument, listed in the `candidates` of the caller's `synthetic` object. `CandidateLegs.read` turns each candidate into a full request body, starting from the caller's own body and replacing only what the candidate names. This program writes one such request by hand, buying three stocks with the same product and order type but a different quantity each, and one of them sold instead.

Nothing is read from a store and nothing is sent. Notice that each body keeps the parent's product and order type unless its candidate overrides them, that the `synthetic` object itself is removed so a leg is an ordinary order, and that the candidates come back in the order they were given. The program also calls `one` directly for a single candidate, which is what `read` does for each.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/candidate_legs/CandidateLegs/example_1_a_basket_of_three.py
"""

from unified_broker_interface.utilities.order_engine.utilities.candidate_legs import (
    CandidateLegs,
)


class BasketOfThreeExample:
    """Reads a basket's candidates and prints the body built for each.

    Attributes:
        candidate_legs (CandidateLegs): The reader being shown.
        body (dict): The caller's request body.
    """

    def __init__(self):
        """Builds the reader and the request body.

        Returns:
            None: This method returns nothing.
        """
        self.candidate_legs = CandidateLegs()
        self.body = {
            'transaction_type': 'BUY',
            'product': 'CNC',
            'order_type': 'MARKET',
            'validity': 'DAY',
            'quantity': 1,
            'tag': 'basket7',
            'synthetic': {
                'type': 'basket',
                'candidates': [
                    {
                        'instrument_id': '11111111-1111-5111-8111-000000000001',
                        'quantity': 10,
                    },
                    {
                        'instrument_id': '11111111-1111-5111-8111-000000000006',
                        'quantity': 25,
                        'order_type': 'LIMIT',
                        'price': '1512.40',
                    },
                    {
                        'instrument_id': '11111111-1111-5111-8111-000000000007',
                        'quantity': 40,
                        'transaction_type': 'SELL',
                    },
                ],
            },
        }

    def run(self):
        """Prints each candidate's body, then one read on its own.

        Returns:
            None: This method returns nothing.
        """
        parameters = self.body['synthetic']
        candidates = self.candidate_legs.read(parameters, self.body)
        for instrument_id, leg_body in candidates:
            print(f'{instrument_id}: {leg_body}')
        seen = set()
        extra = {
            'instrument_id': '11111111-1111-5111-8111-000000000008',
            'quantity': 5,
            'tag': 'hedge1',
        }
        instrument_id, leg_body = self.candidate_legs.one(extra, self.body, 3, seen)
        print(f'one on its own: {instrument_id}: {leg_body}')
        print(f'Instruments now seen: {sorted(seen)}')


if __name__ == '__main__':
    BasketOfThreeExample().run()
