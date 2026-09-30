"""Reads the order books and positions again after the panic button acted, to see what is still live and what is still held.

After sending the cancels, the flatten route reads the order books again and asks `still_open` which of the cancelled orders a broker still reports as live; it waits and asks again until that list is empty. After the closing orders it does the same with `still_held`. An entry that has disappeared counts as done, as does an order whose status has become finished according to `is_finished`.

Quantities arrive as numbers or text depending on the broker, and `whole` reads either as a signed whole number, giving 0 for anything it cannot read. The books are shapes the brokers' scripts store; no Redis is used and nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/kill_switch/KillSwitch/example_2_waiting_for_confirmation.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.kill_switch import (
    KillSwitch,
)


class WaitingForConfirmationExample:
    """Checks a second read of the books against what was cancelled and closed.

    Attributes:
        kill_switch (KillSwitch): The kill switch.
        cancelled (list): The orders the first read said to cancel.
        closed (list): The positions whose closing orders were accepted.
    """

    def __init__(self):
        """Plans from a first read of the books.

        Returns:
            None: This method returns nothing.
        """
        self.kill_switch = KillSwitch([
            'zerodha',
        ])
        first_orders = {
            'zerodha': {
                'A1': {
                    'order': {
                        'status': 'OPEN',
                    },
                },
                'A2': {
                    'order': {
                        'status': 'OPEN',
                    },
                },
                'A3': {
                    'order': {
                        'status': 'PENDING',
                    },
                },
            },
        }
        first_positions = {
            'zerodha': {
                'INFY': {
                    'position': {
                        'tradingsymbol': 'INFY',
                        'quantity': 5,
                    },
                },
                'TCS': {
                    'position': {
                        'tradingsymbol': 'TCS',
                        'quantity': -3,
                    },
                },
            },
        }
        self.cancelled = self.kill_switch.orders_to_cancel(first_orders)
        self.closed = self.kill_switch.positions_to_close(first_positions)

    def run(self):
        """Prints what is still open and still held on the second read, then shows the helpers.

        Returns:
            None: This method returns nothing.
        """
        second_orders = {
            'zerodha': {
                'A1': {
                    'order': {
                        'status': 'CANCELLED',
                    },
                },
                'A2': {
                    'order': {
                        'status': 'OPEN',
                    },
                },
            },
        }
        second_positions = {
            'zerodha': {
                'INFY': {
                    'position': {
                        'quantity': 0,
                    },
                },
                'TCS': {
                    'position': {
                        'quantity': '-3',
                    },
                },
            },
        }
        print(f'Asked to cancel: {len(self.cancelled)} orders; still open: {self.kill_switch.still_open(second_orders, self.cancelled)}')
        print(f'Asked to close: {len(self.closed)} positions; still held: {self.kill_switch.still_held(second_positions, self.closed)}')
        statuses = [
            'EXPIRED',
            'OPEN',
        ]
        for status in statuses:
            print(f'is_finished({status}): {self.kill_switch.is_finished(status)}')
        values = [
            '-75',
            12.0,
            None,
            'lots',
        ]
        for value in values:
            print(f'whole({value!r}): {self.kill_switch.whole(value)}')


if __name__ == '__main__':
    WaitingForConfirmationExample().run()
