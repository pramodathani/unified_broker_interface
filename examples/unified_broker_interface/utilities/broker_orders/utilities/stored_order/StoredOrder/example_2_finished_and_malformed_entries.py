"""Shows which stored orders count as finished, and how a malformed entry is read without failing.

A cancel or modification of an order that is `COMPLETE`, `CANCELLED`, `REJECTED` or `EXPIRED` is refused without calling the broker, because the order can never change again. `is_finished` makes that decision. An order still `TRIGGER PENDING` is not finished.

Redis can also hold an entry whose `order` or `data` is not a dictionary, for example after a broker changed its payload. `StoredOrder` then reads both as empty dictionaries and the status as None, so the route can answer with a clear refusal instead of crashing. This entry shape is one `test_runs/order_routes.py` stores on purpose.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/stored_order/StoredOrder/example_2_finished_and_malformed_entries.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    StoredOrder,
)


class FinishedAndMalformedEntriesExample:
    """Checks several statuses and one malformed entry.

    Attributes:
        statuses (list): The normalized statuses to check.
    """

    def __init__(self):
        """Lists the statuses to check.

        Returns:
            None: This method returns nothing.
        """
        self.statuses = [
            'OPEN',
            'TRIGGER PENDING',
            'COMPLETE',
            'CANCELLED',
            'REJECTED',
            'EXPIRED',
        ]

    def run(self):
        """Prints whether each status is finished, then what a malformed entry reads as.

        Returns:
            None: This method returns nothing.
        """
        for status in self.statuses:
            entry = {
                'order': {
                    'status': status,
                },
                'data': {},
            }
            stored_order = StoredOrder(entry)
            print(f'{status}: finished={stored_order.is_finished()}')
        malformed = StoredOrder({
            'order': 'not a dictionary',
            'data': 'not a dictionary',
        })
        print(f'Malformed entry: order={malformed.order}, data={malformed.data}, status={malformed.status}, finished={malformed.is_finished()}')


if __name__ == '__main__':
    FinishedAndMalformedEntriesExample().run()
