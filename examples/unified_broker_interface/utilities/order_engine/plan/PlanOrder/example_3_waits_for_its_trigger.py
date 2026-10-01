"""Arms a plan that waits for the price to touch a level, walks it through price ticks, and shows it firing once.

A `PlanOrder` whose order has a trigger answers `202 armed` and places nothing. The order engine's price ticker then hands it every tick through `on_price_tick`, and the first tick on which the trigger holds places the order, priced at that moment. The clock ticker also calls `on_clock_tick` every second, which ends any order whose lifetime is up. This plan uses the `market_if_touched` preset: a buy waiting for the last price to fall to 1,400, which then takes the offer two ticks through.

The engine's placement is a small stand-in that always chooses Zerodha and accepts every order, and the event log is the `RecordingEventLog` stand-in from the offline suites, so nothing leaves the machine. The ticks are quotes written out here, and RELIANCE's tick size is 0.10.

`quotes_now` reads the quote an order placed outside a tick is priced from, which the stand-in has none of, and `part_record` and `set_part_record` read and write one part's record, which the parts use to keep their state; a record written with no message is kept in the parameters without an event. `closes_position` says whether a leg may use the part of a broker's daily cap kept for exits; this plan's order opens a position, so it does not, while a plan whose order has the `protect` side, shown last, does.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/plan/PlanOrder/example_3_waits_for_its_trigger.py
"""

import logging
import time

from test_runs.engine_stand_ins import (
    RecordingEventLog,
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


class WaitsForItsTriggerExample:
    """Arms a market-if-touched plan and walks it through three ticks.

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
        self.event_log = RecordingEventLog()

    def intent(self, plan):
        """The intent for ten RELIANCE shares at 1,402.50, described by a plan.

        Args:
            plan (dict): The `plan` object.

        Returns:
            dict: The intent.
        """
        return {
            'intent_id': 'intent-1',
            'instrument_id': INSTRUMENT_ID,
            'body': {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'BUY',
                'product': 'MIS',
                'order_type': 'LIMIT',
                'quantity': 10,
                'price': '1402.50',
                'synthetic': {
                    'type': 'plan',
                    'plan': plan,
                },
            },
        }

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

    def run(self):
        """Arms the plan, gives it three ticks, and prints what it did.

        Returns:
            None: This method returns nothing.
        """
        intent = self.intent({
            'order': {
                'presets': [
                    {
                        'market_if_touched': {
                            'trigger_price': 1400,
                        },
                    },
                ],
            },
        })
        runner = PlanOrder.started(
            intent,
            self.placement,
            self.event_log,
            StandInParentStore(),
            logging.getLogger('example'),
        )
        body, status = runner.run(intent, time.perf_counter())
        print(f"Answer: HTTP {status}, {body['outcome']}: {body['status_message']}")
        print(f"Parts: {runner.parent.parameters['parts']}")
        print(f'Quotes it would price an order placed now from: {runner.quotes_now()}')
        for seconds, bid, offer in ((1, 1402.40, 1402.50), (2, 1399.90, 1400.00), (3, 1399.80, 1399.90)):
            quotes = {
                INSTRUMENT_ID: self.quote(bid, offer),
            }
            acted = runner.on_price_tick(quotes, 1790000000.0 + seconds)
            print(f'tick {seconds}, offer {offer}: placed {acted}, sent so far {self.placement.sent}')
        print(f'A clock tick, which only ends orders whose lifetime is up, and this plan has none: {runner.on_clock_tick(1790000010.0)}')
        record = runner.part_record('root')
        print(f'The root part\'s record: {record}')
        record['note'] = 'kept only in the parameters'
        runner.set_part_record('root', record, None)
        print(f"Parts: {runner.parent.parameters['parts']}")
        print(f'Parent: {runner.parent.state}')
        print(f"Its order closes a position: {runner.closes_position('root')}")
        protecting = self.intent({
            'order': {
                'side': 'protect',
            },
        })
        protecting_runner = PlanOrder.started(
            protecting,
            self.placement,
            RecordingEventLog(),
            StandInParentStore(),
            logging.getLogger('example'),
        )
        print(f"A protecting plan's order closes a position: {protecting_runner.closes_position('root')}")


if __name__ == '__main__':
    WaitsForItsTriggerExample().run()
