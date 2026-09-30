"""Builds the form-encoded place request Flattrade is sent, and shows what a dry run answers with.

A `BrokerRequest` carries everything the HTTP call needs, including the session headers that hold the broker's credentials. A dry run must not show those, so `shown` returns only the method, the URL and the body. For a broker whose body is a form, the broker order class also stores the readable form fields in `shown_form`, and `shown` answers with those under `form`.

The fields below are the ones Flattrade's `PlaceOrder` endpoint received in `test_runs/fixtures/order_routes.jsonl`. Nothing is sent: the program only builds the object and prints it.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/broker_request/BrokerRequest/example_1_form_body_dry_run.py
"""

import json

from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)


class FormBodyDryRunExample:
    """Builds a Flattrade place request and prints the part a dry run shows.

    Attributes:
        broker_request (BrokerRequest): The request being shown.
    """

    def __init__(self):
        """Builds the request with a form body and a secret-looking header.

        Returns:
            None: This method returns nothing.
        """
        form = {
            'uid': 'FT000001',
            'actid': 'FT000001',
            'exch': 'NSE',
            'tsym': 'RELIANCE-EQ',
            'qty': '10',
            'prc': '0',
            'trgprc': '0',
            'dscqty': '0',
            'prd': 'I',
            'trantype': 'B',
            'prctyp': 'MKT',
            'ret': 'DAY',
            'amo': 'NO',
            'ordersource': 'API',
        }
        encoded_body = 'jData=' + json.dumps(form) + '&jKey=example-session-token'
        self.broker_request = BrokerRequest(
            'POST',
            'https://piconnect.flattrade.in/PiConnectAPI/PlaceOrder',
            {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            data=encoded_body,
            shown_form=form,
        )

    def run(self):
        """Prints the request's fields and its dry-run form.

        Returns:
            None: This method returns nothing.
        """
        print(f'Method: {self.broker_request.method}')
        print(f'Checks the certificate: {self.broker_request.verify_certificate}')
        print(f'Headers kept for sending: {sorted(self.broker_request.headers)}')
        print('What a dry run shows:')
        print(json.dumps(self.broker_request.shown(), indent=2, sort_keys=True))


if __name__ == '__main__':
    FormBodyDryRunExample().run()
