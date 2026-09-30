"""Builds a `RefusedRequestError` from a ready-made body, and compares it with one built by `refusal`.

The constructor takes the whole JSON body and the status. Its message, which is what `str(error)` prints and what a log line shows, is read from the body's `error` field. `refusal` is the shorter way to build the same thing when the body is just a message plus a few fields.

The program builds a "not mapped" refusal both ways and shows that they carry the same body and status.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/refused_request/RefusedRequestError/example_2_building_one_directly.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)


class BuildingOneDirectlyExample:
    """Builds the same refusal in the two available ways and compares them.

    Attributes:
        direct (RefusedRequestError): The refusal built with the constructor.
        built (RefusedRequestError): The refusal built with `refusal`.
    """

    def __init__(self):
        """Builds both refusals.

        Returns:
            None: This method returns nothing.
        """
        body = {
            'error': 'the instrument is not mapped',
            'instrument_id': '11111111-1111-5111-8111-000000000001',
        }
        self.direct = RefusedRequestError(body, 404)
        self.built = RefusedRequestError.refusal(
            'the instrument is not mapped',
            404,
            instrument_id='11111111-1111-5111-8111-000000000001',
        )

    def run(self):
        """Prints both refusals and whether they match.

        Returns:
            None: This method returns nothing.
        """
        print(f'Direct: status={self.direct.status}, message={self.direct}, body={self.direct.body}')
        print(f'Built: status={self.built.status}, message={self.built}, body={self.built.body}')
        same_body = self.direct.body == self.built.body
        same_status = self.direct.status == self.built.status
        print(f'Same body: {same_body}, same status: {same_status}')


if __name__ == '__main__':
    BuildingOneDirectlyExample().run()
