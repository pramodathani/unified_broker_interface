"""Shows how the engine answers intents it cannot place, so that one bad order never stops the orders behind it.

`finish_intent` answers one intent, pushes the answer and acknowledges the entry whatever happened. This program hands it three intents that go wrong in different ways. The first names an order type the engine does not run, which is the caller's mistake and is answered 400. The second fails while its broker is being chosen, before anything was sent, so the engine can say for certain that nothing was placed and answers 503. The third fails while its request is in flight to the broker, after the leg was recorded, so nobody knows whether the order exists and the answer is 504. Its record ends at `leg_requested`, which is exactly what recovery looks for at the next start. The first message is cut before its long list of every order type the engine runs.

It then shows the smaller pieces. `take_intent` acknowledges an entry that does not hold an intent instead of reading it again for ever, `decode` is what tells such an entry apart, `count_refused` is the counter every refusal adds to, and `add_refusal_reason` copies the brokers' reasons from the legs into a refused answer that left them out, as a combined order such as a ladder can.

Redis is the in-memory `FakeEngineStoreRedis` from `test_runs/redis_stand_ins.py` and the event log is `RecordingEventLog` from `test_runs/engine_stand_ins.py`. The placement is a small class defined here whose behaviour depends on the quantity asked for, so each failure can be produced on purpose; nothing reaches a broker. The logger is a small class that counts what was logged, because the engine logs failures with their tracebacks.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_runner/OrderEngine/example_3_refusals_and_failures.py
"""

import json

from test_runs.engine_stand_ins import (
    RecordingEventLog,
)
from test_runs.redis_stand_ins import (
    FakeEngineStoreRedis,
)
from unified_broker_interface.utilities.order_engine.utilities.engine_runner import (
    OrderEngine,
)
from unified_broker_interface.utilities.order_engine.utilities.intent_handoff import (
    INTENT_STREAM_FIELD,
    INTENT_STREAM_KEY,
)
from unified_broker_interface.utilities.order_engine.utilities.order_intent import (
    OrderIntent,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    ParentStore,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'
FAILS_WHILE_CHOOSING = 13
FAILS_WHILE_SENDING = 7


class StandInBrokerRequest:
    """A request built for a broker, reduced to what the engine records from it.

    Attributes:
        tag (str | None): The tag the request carries.
    """

    def __init__(self, tag):
        """Builds the request.

        Args:
            tag (str | None): The tag the request carries.

        Returns:
            None: This method returns nothing.
        """
        self.tag = tag

    def shown(self):
        """The request as the event log keeps it.

        Returns:
            dict: The method and URL.
        """
        return {
            'method': 'POST',
            'url': 'https://broker.example/orders',
        }


class StandInPreparedPlacement:
    """An order given a broker and a request, but not yet sent.

    Attributes:
        broker_name (str): The chosen broker.
        broker_request (StandInBrokerRequest): The request built for it.
        identifier_sent (str): The symbol the request names the instrument by.
    """

    def __init__(self, broker_request):
        """Builds the prepared placement for Kotak.

        Args:
            broker_request (StandInBrokerRequest): The request built for it.

        Returns:
            None: This method returns nothing.
        """
        self.broker_name = 'kotak'
        self.broker_request = broker_request
        self.identifier_sent = 'RELIANCE-EQ'


class MisbehavingPlacement:
    """Stands in for the engine's placement, failing on purpose for particular quantities.

    Attributes:
        quantity (int | None): The quantity of the order last prepared.
        requests_in_flight (int): How many requests were handed to the stand-in broker.
    """

    def __init__(self):
        """Builds the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.quantity = None
        self.requests_in_flight = 0

    def prepare(self, order, instrument_id, broker_name=None):
        """Chooses Kotak, unless the quantity is the one that fails here.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument_id (str): The instrument, unused by the stand-in.
            broker_name (str | None): The broker the order must go to, unused by the stand-in.

        Returns:
            StandInPreparedPlacement: The prepared order.

        Raises:
            KeyError: When the quantity is `FAILS_WHILE_CHOOSING`, as a missing catalogue entry would.
        """
        del instrument_id, broker_name
        if order.quantity == FAILS_WHILE_CHOOSING:
            raise KeyError('kotak')
        self.quantity = order.quantity
        return StandInPreparedPlacement(StandInBrokerRequest(order.tag))

    def send(self, prepared_placement, started_at):
        """Sends the order, timing out when the quantity is the one that fails here.

        Args:
            prepared_placement (StandInPreparedPlacement): The prepared order.
            started_at (float): When the engine took the intent, unused.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            TimeoutError: When the quantity is `FAILS_WHILE_SENDING`, as a broker that never answers would.
        """
        del prepared_placement, started_at
        self.requests_in_flight = self.requests_in_flight + 1
        if self.quantity == FAILS_WHILE_SENDING:
            raise TimeoutError('the broker did not answer')
        return {
            'broker': 'kotak',
            'outcome': 'accepted',
            'order_id': '260930000077',
        }, 200


class CountingLogger:
    """A stand-in logger that counts what it is given.

    Attributes:
        messages (int): How many messages were logged.
    """

    def __init__(self):
        """Builds the logger.

        Returns:
            None: This method returns nothing.
        """
        self.messages = 0

    def info(self, message):
        """Counts an informational message.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        del message
        self.messages = self.messages + 1

    def error(self, message):
        """Counts an error.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        del message
        self.messages = self.messages + 1

    def exception(self, message):
        """Counts an error logged while handling an exception.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        del message
        self.messages = self.messages + 1


class RefusalsAndFailuresExample:
    """Hands the engine intents that fail in different ways and prints each answer.

    Attributes:
        cache (FakeEngineStoreRedis): The stand-in Redis.
        placement (MisbehavingPlacement): The stand-in placement.
        event_log (RecordingEventLog): The stand-in record.
        engine (OrderEngine): The engine being shown.
    """

    def __init__(self):
        """Builds the engine over the stand-ins.

        Returns:
            None: This method returns nothing.
        """
        self.cache = FakeEngineStoreRedis()
        self.placement = MisbehavingPlacement()
        self.event_log = RecordingEventLog()
        self.engine = OrderEngine(
            self.cache,
            self.placement,
            None,
            CountingLogger(),
            30.0,
            300,
            self.event_log,
            ParentStore(self.cache),
        )
        self.engine.ensure_group()

    def intent(self, name, quantity, synthetic=None):
        """Builds one intent for a market buy of RELIANCE.

        Args:
            name (str): A short name, which becomes the intent's id.
            quantity (int): The quantity, which decides how the stand-in behaves.
            synthetic (dict | None): The order type the body asks for, or None for a plain order.

        Returns:
            dict: The intent document.
        """
        body = {
            'instrument_id': INSTRUMENT_ID,
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': quantity,
        }
        if synthetic is not None:
            body['synthetic'] = synthetic
        intent = OrderIntent(body, INSTRUMENT_ID, 5.0)
        intent.intent_id = name
        intent.reply_key = f'unified:orders:intents:result:{name}'
        return intent.document()

    def finish(self, intent):
        """Writes one intent to the stream, reads it back, lets `finish_intent` answer it and prints the answer.

        Args:
            intent (dict): The intent document.

        Returns:
            None: This method returns nothing.
        """
        entry_id = self.cache.xadd(INTENT_STREAM_KEY, {
            INTENT_STREAM_FIELD: json.dumps(intent),
        })
        self.engine.read(False)
        self.engine.finish_intent(entry_id, intent, None)
        answer = json.loads(self.cache.lists[intent['reply_key']][0])
        body = answer['body']
        message = body['error'].split('; it runs ')[0]
        print(f'{intent["intent_id"]}: {answer["status"]} {message}')

    def run(self):
        """Answers the failing intents, then shows the smaller pieces.

        Returns:
            None: This method returns nothing.
        """
        self.finish(self.intent('unknown_type', 10, {
            'type': 'teleport',
        }))
        self.finish(self.intent('fails_while_choosing', FAILS_WHILE_CHOOSING))
        self.finish(self.intent('fails_while_sending', FAILS_WHILE_SENDING))
        print(f'Requests that reached the stand-in broker: {self.placement.requests_in_flight}')
        events = []
        for event in self.event_log.events:
            events.append(f'{event["event"]}:{event.get("parent_state")}')
        print(f'Recorded: {events}')
        print(f'Placed {self.engine.placed}, refused {self.engine.refused}')

        entry_id = self.cache.xadd(INTENT_STREAM_KEY, {
            INTENT_STREAM_FIELD: '{"body": {}}',
        })
        entry = self.engine.read(False)[0]
        print(f'Decoded entry without a reply key: {self.engine.decode(entry[2])}')
        print(f'Decoded missing entry: {self.engine.decode(None)}')
        self.engine.take_intent(entry_id, entry[2])
        print(f'Unacknowledged entries: {self.cache.pending[INTENT_STREAM_KEY]}')

        self.engine.count_refused()
        print(f'Refused after one more: {self.engine.refused}')

        runner = self.engine.synthetic_order(self.intent('ladder', 20))
        first_leg = OrderLeg(f'{runner.parent.parent_order_id}:1', 'entry')
        first_leg.status_message = 'RMS: margin exceeds available funds'
        second_leg = OrderLeg(f'{runner.parent.parent_order_id}:2', 'entry')
        second_leg.status_message = 'RMS: margin exceeds available funds'
        runner.parent.legs.append(first_leg)
        runner.parent.legs.append(second_leg)
        body = {
            'outcome': 'rejected',
        }
        self.engine.add_refusal_reason(runner, body, 400)
        print(f'Refused answer with the legs\' reasons added: {body}')
        accepted_body = {
            'outcome': 'accepted',
        }
        self.engine.add_refusal_reason(runner, accepted_body, 200)
        print(f'Accepted answer is left alone: {accepted_body}')


if __name__ == '__main__':
    RefusalsAndFailuresExample().run()
