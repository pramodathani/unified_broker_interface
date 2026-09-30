"""Shows how `shown` treats a JSON body and a request that carries only query parameters.

A broker such as Dhan takes its order as a JSON body, which `shown` answers with under `json`. A cancel for a broker such as Zerodha has no body at all: its order id travels in the URL and, for some brokers, in query parameters, which `shown` answers with under `params`. The `tag` attribute records the tag the broker actually receives, which is how Groww's generated tag reaches the caller.

The payloads are the shapes recorded in `test_runs/fixtures/order_routes.jsonl`. Nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/broker_request/BrokerRequest/example_2_json_and_query_requests.py
"""

import json

from unified_broker_interface.utilities.broker_orders.utilities.broker_request import (
    BrokerRequest,
)


class JsonAndQueryRequestsExample:
    """Builds a JSON request and a query-only request and prints what a dry run shows of each.

    Attributes:
        json_request (BrokerRequest): A Dhan place request with a JSON body.
        query_request (BrokerRequest): A cancel whose only fields are query parameters.
    """

    def __init__(self):
        """Builds both requests.

        Returns:
            None: This method returns nothing.
        """
        self.json_request = BrokerRequest(
            'POST',
            'https://api.dhan.co/v2/orders',
            {
                'access-token': 'example-token',
            },
            json_body={
                'dhanClientId': '1000000001',
                'transactionType': 'BUY',
                'exchangeSegment': 'NSE_EQ',
                'productType': 'INTRADAY',
                'orderType': 'MARKET',
                'validity': 'DAY',
                'securityId': '2885',
                'quantity': 10,
                'price': 0.0,
            },
            tag='swing01',
        )
        self.query_request = BrokerRequest(
            'DELETE',
            'https://api.example-broker.in/orders/cancel',
            {
                'Authorization': 'example-token',
            },
            params={
                'order_id': '250930000000001',
                'segment': 'CASH',
            },
        )

    def run(self):
        """Prints each request's dry-run form and the tag the JSON request carries.

        Returns:
            None: This method returns nothing.
        """
        print('JSON body request:')
        print(json.dumps(self.json_request.shown(), indent=2, sort_keys=True))
        print(f'Tag the broker receives: {self.json_request.tag}')
        print('Query-only request:')
        print(json.dumps(self.query_request.shown(), indent=2, sort_keys=True))
        print(f'Tag the broker receives: {self.query_request.tag}')


if __name__ == '__main__':
    JsonAndQueryRequestsExample().run()
