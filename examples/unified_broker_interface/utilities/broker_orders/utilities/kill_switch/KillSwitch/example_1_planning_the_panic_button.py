"""Works out what the panic button has to cancel and what it has to close, from order books and positions read from Redis.

`KillSwitch` decides and never acts: the flatten route reads each broker's order book and positions, asks the kill switch what to do, sends the cancels, waits for them to be confirmed, and only then sends the closing orders. Cancelling first matters because a resting stop that is still live when a position is closed can fill afterwards and open a new position the other way.

`orders_to_cancel` keeps every order that is not finished, including one whose status no broker's vocabulary recognises, since cancelling something already finished costs a refusal while leaving something live costs a position. `positions_to_close` keeps every NET position that is not flat, with the side and size of the order that closes it; a DAY row repeats a NET holding and is left out so the trade is not doubled.

The books below are shapes the brokers' order and position scripts store. No Redis is used and nothing is sent.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/kill_switch/KillSwitch/example_1_planning_the_panic_button.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.kill_switch import (
    KillSwitch,
)


class PlanningThePanicButtonExample:
    """Plans the cancels and closes for two brokers.

    Attributes:
        kill_switch (KillSwitch): The kill switch.
        order_books (dict): Each broker's decoded order entries.
        position_books (dict): Each broker's decoded position entries.
    """

    def __init__(self):
        """Builds the kill switch and the books.

        Returns:
            None: This method returns nothing.
        """
        broker_names = [
            'dhan',
            'zerodha',
        ]
        self.kill_switch = KillSwitch(broker_names)
        self.order_books = {
            'zerodha': {
                '250915000000011': {
                    'order': {
                        'status': 'OPEN',
                    },
                },
                '250915000000012': {
                    'order': {
                        'status': 'COMPLETE',
                    },
                },
                '250915000000013': {
                    'order': {
                        'status': 'trigger pending',
                    },
                },
            },
            'dhan': {
                '112509150000012': {
                    'order': {
                        'status': 'CANCELLED',
                    },
                },
            },
        }
        self.position_books = {
            'zerodha': {
                'NSE:RELIANCE:MIS:NET': {
                    'position': {
                        'day_or_net': 'NET',
                        'instrument_token': '738561',
                        'tradingsymbol': 'RELIANCE',
                        'exchange': 'NSE',
                        'product': 'MIS',
                        'quantity': 10,
                    },
                },
                'NSE:RELIANCE:MIS:DAY': {
                    'position': {
                        'day_or_net': 'DAY',
                        'tradingsymbol': 'RELIANCE',
                        'quantity': 10,
                    },
                },
            },
            'dhan': {
                'NSE_FNO:43210:MARGIN': {
                    'position': {
                        'instrument_token': '43210',
                        'tradingsymbol': 'NIFTY-Oct2026-25000-CE',
                        'exchange': 'NSE',
                        'segment': 'NSE_FNO',
                        'product': 'NRML',
                        'quantity': '-75',
                    },
                },
                'NSE_EQ:2885:INTRADAY': {
                    'position': {
                        'tradingsymbol': 'RELIANCE',
                        'quantity': 0,
                    },
                },
            },
        }

    def run(self):
        """Prints the cancels first and the closes second.

        Returns:
            None: This method returns nothing.
        """
        print('1. Cancel:')
        for order in self.kill_switch.orders_to_cancel(self.order_books):
            print(f'   {order["broker"]} {order["order_id"]} ({order["status"]})')
        print('2. Wait until every cancel is confirmed.')
        print('3. Close:')
        for position in self.kill_switch.positions_to_close(self.position_books):
            print(f'   {position["broker"]} {position["tradingsymbol"]} {position["product"]}: holds {position["quantity"]}, send {position["transaction_type"]} {position["close_quantity"]}')


if __name__ == '__main__':
    PlanningThePanicButtonExample().run()
