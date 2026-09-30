"""Shows the candidate lists `CandidateLegs.read` refuses, each with the HTTP 400 answer the order route sends back.

Every order in a multi-instrument group has to be told apart from the others afterwards, and each has to name its instrument by id, because the engine does not look instruments up by symbol. This program sends five bad `synthetic` objects to `CandidateLegs.read`: one with no candidates, one with twenty-six (one more than the limit of twenty-five), one whose candidate is a bare string, one whose candidate names no instrument, and one that names the same instrument twice.

Each refusal is a `RefusedRequestError` whose `status` and `body` are what the route answers with. Nothing is read from a store and nothing is sent. Notice that the message counts candidates from 1, as a caller reading their own list would.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/candidate_legs/CandidateLegs/example_2_candidates_that_are_refused.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.candidate_legs import (
    CandidateLegs,
)

RELIANCE = '11111111-1111-5111-8111-000000000001'


class RefusedCandidatesExample:
    """Reads bad candidate lists and prints each refusal.

    Attributes:
        candidate_legs (CandidateLegs): The reader being shown.
        body (dict): The caller's request body, shared by every attempt.
        attempts (list): Pairs of (description, synthetic parameters).
    """

    def __init__(self):
        """Builds the reader, the body and the bad parameter sets.

        Returns:
            None: This method returns nothing.
        """
        self.candidate_legs = CandidateLegs()
        self.body = {
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 1,
        }
        too_many = []
        for number in range(26):
            too_many.append({
                'instrument_id': f'11111111-1111-5111-8111-{number:012d}',
                'quantity': 1,
            })
        self.attempts = [
            (
                'no candidates',
                {
                    'type': 'basket',
                },
            ),
            (
                'twenty-six candidates',
                {
                    'type': 'basket',
                    'candidates': too_many,
                },
            ),
            (
                'a candidate that is a string',
                {
                    'type': 'basket',
                    'candidates': [
                        RELIANCE,
                    ],
                },
            ),
            (
                'a candidate with no instrument',
                {
                    'type': 'basket',
                    'candidates': [
                        {
                            'instrument_id': RELIANCE,
                            'quantity': 5,
                        },
                        {
                            'quantity': 5,
                        },
                    ],
                },
            ),
            (
                'the same instrument twice',
                {
                    'type': 'oca',
                    'candidates': [
                        {
                            'instrument_id': RELIANCE,
                            'quantity': 5,
                        },
                        {
                            'instrument_id': RELIANCE,
                            'quantity': 5,
                            'transaction_type': 'SELL',
                        },
                    ],
                },
            ),
        ]

    def run(self):
        """Prints each attempt's refusal.

        Returns:
            None: This method returns nothing.
        """
        for description, parameters in self.attempts:
            try:
                self.candidate_legs.read(parameters, self.body)
            except RefusedRequestError as error:
                print(f'{description}: refused with {error.status}: {error.body["error"]}')


if __name__ == '__main__':
    RefusedCandidatesExample().run()
