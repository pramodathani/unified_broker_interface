"""Holds a buy of ten RELIANCE in the engine until its limit is marketable, changes it while held, and shows it sent at the new terms.

A plan with the `virtual_limit` preset waits on a `limit_marketable` trigger and answers `202 armed`. `PlanOrder.modify_held`, which `PUT /api/orders/modify` reaches with the parent's id, checks a change first with `dry_run`, refuses a price that is not a whole number of ticks, and otherwise keeps the new price and quantity in the order's part record and in the held terms the virtual book follows, sending nothing. When the offer reaches the new limit, the order goes out at the new price and quantity, and from then on it can only be changed at its broker, so a further change by parent id is refused with `409`.

The engine's placement is a small stand-in that always chooses Zerodha and accepts every order, and the event log is the `RecordingEventLog` stand-in from the offline suites, so nothing leaves the machine. RELIANCE's tick size is 0.10.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/plan/PlanOrder/example_4_a_held_order_changed.py
"""

import decimal
import logging
import time

from test_runs.engine_stand_ins import (
    RecordingEventLog,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.order_engine.plan import (
    PlanOrder,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


class StandInBrokerRequest:
    """A request built for a broker, reduced to what the engine reads from it.

    Attributes:
        tag (str | None): The tag the request carries.
        body (dict): The request's body.
    """

    def __init__(self, tag, body):
        """Builds the request.

        Args:
            tag (str | None): The tag the request carries.
            body (dict): The request's body.

        Returns:
            None: This method returns nothing.
        """
        self.tag = tag
        self.body = body

    def shown(self):
        """The request as the event log keeps it.

        Returns:
            dict: The method, URL and body.
        """
        return {
            'method': 'POST',
            'url': 'https://broker.example/orders',
            'json': self.body,
        }


class StandInPreparedPlacement:
    """An order given a broker and a request, but not yet sent.

    Attributes:
        instrument_id (str): The instrument the order is for.
        broker_name (str): The chosen broker.
        broker_request (StandInBrokerRequest): The request built for it.
        identifier_sent (str): The symbol the request names the instrument by.
        skipped (list): The brokers passed over, which is always none here.
    """

    def __init__(self, instrument_id, broker_name, broker_request):
        """Builds the prepared placement.

        Args:
            instrument_id (str): The instrument the order is for.
            broker_name (str): The chosen broker.
            broker_request (StandInBrokerRequest): The request built for it.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = instrument_id
        self.broker_name = broker_name
        self.broker_request = broker_request
        self.identifier_sent = 'RELIANCE'
        self.skipped = []


class StandInPlacement:
    """Stands in for the engine's placement: chooses Zerodha and accepts every order.

    Attributes:
        sent (list): Every order sent, as `(broker, transaction_type, quantity, price)`.
        next_number (int): The number the next broker order id is made from.
    """

    def __init__(self):
        """Builds the stand-in with nothing sent.

        Returns:
            None: This method returns nothing.
        """
        self.sent = []
        self.next_number = 1

    def market_context(self, instrument_id, needs_quote, needs_positions):
        """Answers with RELIANCE on the NSE, whose tick size every broker agrees is 0.10.

        Args:
            instrument_id (str): The instrument.
            needs_quote (bool): Unused, since no quote is served.
            needs_positions (bool): Unused, since no positions are served.

        Returns:
            tuple: The instrument (Instrument), no quote and no positions.
        """
        del needs_quote, needs_positions
        instrument = Instrument(
            instrument_id,
            {
                'segment': 'nse_equities',
            },
            {
                'zerodha': {
                    'order_symbol': 'RELIANCE',
                    'lot_size': 1,
                    'tick_size': '0.10',
                },
            },
        )
        return instrument, None, {
            'net': [],
        }

    def prepare(self, order, instrument_id, broker_name=None):
        """Chooses a broker and builds the request, without sending it.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument_id (str): The instrument.
            broker_name (str | None): The broker the order must go to, or None for Zerodha.

        Returns:
            StandInPreparedPlacement: The prepared order.
        """
        body = {
            'transaction_type': order.transaction_type,
            'quantity': order.quantity,
            'price': str(order.price),
        }
        broker_request = StandInBrokerRequest(order.tag, body)
        return StandInPreparedPlacement(
            instrument_id,
            broker_name or 'zerodha',
            broker_request,
        )

    def dry_run_answer(self, prepared_placement, started_at):
        """Answers with the request that would have been sent.

        Args:
            prepared_placement (StandInPreparedPlacement): The prepared order.
            started_at (float): When the engine took the intent, unused.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        del started_at
        return {
            'broker': prepared_placement.broker_name,
            'dry_run': True,
            'request': prepared_placement.broker_request.shown(),
        }, 200

    def send(self, prepared_placement, started_at):
        """Sends the order to the stand-in broker, which accepts it.

        Args:
            prepared_placement (StandInPreparedPlacement): The prepared order.
            started_at (float): When the engine took the intent, unused.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        del started_at
        body = prepared_placement.broker_request.body
        self.sent.append((
            prepared_placement.broker_name,
            body['transaction_type'],
            body['quantity'],
            body['price'],
        ))
        order_id = f'2609300000{self.next_number:02d}'
        self.next_number = self.next_number + 1
        return {
            'broker': prepared_placement.broker_name,
            'outcome': 'accepted',
            'order_id': order_id,
            'status_message': None,
            'broker_response': {
                'status': 'success',
                'data': {
                    'order_id': order_id,
                },
            },
        }, 200


class StandInParentStore:
    """Stands in for the Redis copy of the parents, keeping nothing."""

    def save(self, parent):
        """Accepts a parent without keeping it.

        Args:
            parent (ParentOrder): The parent.

        Returns:
            None: This method returns nothing.
        """
        del parent


class EmptyCache:
    """Stands in for Redis holding no queue estimate, as when the virtual book is not running."""

    def hget(self, key, field):
        """Reads one hash field, of which there are none.

        Args:
            key (str): Unused.
            field (str): Unused.

        Returns:
            None: There is no estimate.
        """
        del key, field
        return None


class AHeldOrderChangedExample:
    """Changes a held plan order and lets it fire.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
        event_log (RecordingEventLog): Where the events are kept.
    """

    def __init__(self):
        """Builds the stand-ins.

        Returns:
            None: This method returns nothing.
        """
        self.placement = StandInPlacement()
        self.placement.cache = EmptyCache()
        self.event_log = RecordingEventLog()

    def quote(self, bid, offer):
        """A quote with the touch where the program wants it.

        Args:
            bid (float): The best bid.
            offer (float): The best offer.

        Returns:
            dict: The quote.
        """
        return {
            'last_price': offer,
            'depth': {
                'buy': [
                    {
                        'price': bid,
                        'quantity': 100,
                        'orders': 1,
                    },
                ],
                'sell': [
                    {
                        'price': offer,
                        'quantity': 100,
                        'orders': 1,
                    },
                ],
            },
        }

    def show(self, label, runner, price, quantity, dry_run):
        """Asks for one change and prints the answer or the refusal.

        Args:
            label (str): What is being asked.
            runner (PlanOrder): The plan order.
            price (decimal.Decimal | None): The new price, or None.
            quantity (int | None): The new quantity, or None.
            dry_run (bool): Whether only to check it.

        Returns:
            None: This method returns nothing.
        """
        try:
            body, status = runner.modify_held(price, quantity, dry_run)
        except RefusedRequestError as error:
            print(f'{label}: HTTP {error.status}, {error.body["error"]}')
            return
        print(f'{label}: HTTP {status}, {body["quantity"]} at {body["price"]}, {body["status_message"]}')

    def run(self):
        """Arms the plan, changes it, and ticks it.

        Returns:
            None: This method returns nothing.
        """
        intent = {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'quantity': 10,
                'price': '1400.00',
                'synthetic': {
                    'type': 'plan',
                    'plan': {
                        'order': {
                            'presets': [
                                {
                                    'virtual_limit': {},
                                },
                            ],
                        },
                    },
                },
            },
        }
        runner = PlanOrder.started(
            intent,
            self.placement,
            self.event_log,
            StandInParentStore(),
            logging.getLogger('example'),
        )
        body, status = runner.run(intent, time.perf_counter())
        print(f"Answer: HTTP {status}, {body['outcome']}")
        self.show('A dry run of 20 at 1,401.00', runner, decimal.Decimal('1401.00'), 20, True)
        self.show('A price between ticks', runner, decimal.Decimal('1401.05'), None, False)
        self.show('20 at 1,401.00', runner, decimal.Decimal('1401.00'), 20, False)
        print(f"Held terms the virtual book follows: {runner.part_record('root')['memory']['trigger']['held']}")
        quotes = {
            INSTRUMENT_ID: self.quote(1400.90, 1401.00),
        }
        print(f'The offer reaches 1,401.00: placed {runner.on_price_tick(quotes, 1790000001.0)}, sent {self.placement.sent}')
        self.show('Another change once sent', runner, decimal.Decimal('1400.50'), None, False)


if __name__ == '__main__':
    AHeldOrderChangedExample().run()
