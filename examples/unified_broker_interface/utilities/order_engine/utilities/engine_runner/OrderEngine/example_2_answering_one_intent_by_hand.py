"""Takes one intent through the engine's steps by hand, then shows that reading the same intent again does not place it twice.

`OrderEngine.run` does all of this in a loop; this program calls each step itself so its result can be printed. `read` takes new entries from the stream, `decode` turns an entry into the intent document, `expiry_moment` says when the intent becomes too old to place (the caller's deadline plus the engine's grace, thirty seconds here), and `started_parent_id` and `answer_without_placing` say whether it must be answered without placing. `synthetic_order` builds the runner for the kind of order it asks for, and `answer` places it. `reply` pushes the answer onto the caller's reply list and stores a copy under the intent's id, and `acknowledge` tells the stream the entry is done.

The engine acknowledges an intent only after its answer is pushed, so an engine that stops in between reads the intent again at its next start. The parent was saved with its intent id before the order was sent, so the second reading finds it through `started_parent_id` and answers 409 instead of buying a second time. The stored answer keeps the first reading's 200, because `reply` never overwrites it.

Redis is the in-memory `FakeEngineStoreRedis` from `test_runs/redis_stand_ins.py`, and the event log is `RecordingEventLog` from `test_runs/engine_stand_ins.py`. The placement is a small class defined here that always chooses Zerodha and accepts every order, so nothing reaches a broker. The lock and the logger are never used on these steps, so the program passes a plain `logging` logger and None for the lock. Each parent gets a random id, so the program prints whether one matches rather than the id itself.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_runner/OrderEngine/example_2_answering_one_intent_by_hand.py
"""

import json
import logging
import time

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
    ANSWER_KEY_PREFIX,
    INTENT_STREAM_FIELD,
    INTENT_STREAM_KEY,
)
from unified_broker_interface.utilities.order_engine.utilities.order_intent import (
    OrderIntent,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    ParentStore,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


class StandInBrokerRequest:
    """A request built for a broker, reduced to what the engine records from it.

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
        broker_name (str): The chosen broker.
        broker_request (StandInBrokerRequest): The request built for it.
        identifier_sent (str): The symbol the request names the instrument by.
    """

    def __init__(self, broker_name, broker_request):
        """Builds the prepared placement.

        Args:
            broker_name (str): The chosen broker.
            broker_request (StandInBrokerRequest): The request built for it.

        Returns:
            None: This method returns nothing.
        """
        self.broker_name = broker_name
        self.broker_request = broker_request
        self.identifier_sent = 'RELIANCE'


class StandInPlacement:
    """Stands in for the engine's placement: chooses Zerodha and accepts every order.

    Attributes:
        sent (list): Every order sent, as `(broker, transaction_type, quantity)`.
    """

    def __init__(self):
        """Builds the stand-in with nothing sent.

        Returns:
            None: This method returns nothing.
        """
        self.sent = []

    def prepare(self, order, instrument_id, broker_name=None):
        """Chooses a broker and builds the request, without sending it.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument_id (str): The instrument, unused by the stand-in.
            broker_name (str | None): The broker the order must go to, or None for Zerodha.

        Returns:
            StandInPreparedPlacement: The prepared order.
        """
        del instrument_id
        body = {
            'transaction_type': order.transaction_type,
            'quantity': order.quantity,
        }
        return StandInPreparedPlacement(
            broker_name or 'zerodha',
            StandInBrokerRequest(order.tag, body),
        )

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
        ))
        return {
            'broker': prepared_placement.broker_name,
            'outcome': 'accepted',
            'order_id': '260930000001',
            'status_message': None,
        }, 200


class AnsweringOneIntentByHandExample:
    """Places one intent step by step, then reads it again as a restarted engine would.

    Attributes:
        cache (FakeEngineStoreRedis): The stand-in Redis.
        placement (StandInPlacement): The stand-in placement.
        engine (OrderEngine): The engine being shown.
    """

    def __init__(self):
        """Builds the engine over the stand-ins and writes one intent to the stream.

        Returns:
            None: This method returns nothing.
        """
        logger = logging.getLogger('example')
        logger.setLevel(logging.CRITICAL)
        self.cache = FakeEngineStoreRedis()
        self.placement = StandInPlacement()
        self.engine = OrderEngine(
            self.cache,
            self.placement,
            None,
            logger,
            30.0,
            300,
            RecordingEventLog(),
            ParentStore(self.cache),
        )
        intent = OrderIntent(
            {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'BUY',
                'product': 'CNC',
                'order_type': 'MARKET',
                'quantity': 25,
            },
            INSTRUMENT_ID,
            5.0,
        )
        intent.intent_id = '0a1b2c3d4e5f60718293a4b5c6d7e8f9'
        intent.reply_key = 'unified:orders:intents:result:' + intent.intent_id
        self.cache.xadd(INTENT_STREAM_KEY, {
            INTENT_STREAM_FIELD: json.dumps(intent.document()),
        })

    def run(self):
        """Reads, checks, places, answers and acknowledges the intent, then reads it again.

        Returns:
            None: This method returns nothing.
        """
        self.engine.ensure_group()
        entries = self.engine.read(False)
        stream_key, entry_id, fields = entries[0]
        print(f'Read entry {entry_id} from {stream_key}')

        intent = self.engine.decode(fields)
        print(f'Intent {intent["intent_id"]} asks for a {intent["synthetic_type"]} order')
        grace = self.engine.expiry_moment(intent) - intent['deadline_at']
        print(f'Too old to place {grace} seconds after its deadline')
        print(f'Already started a parent: {self.engine.started_parent_id(intent)}')
        print(f'Must be answered without placing: {self.engine.answer_without_placing(intent)}')

        runner = self.engine.synthetic_order(intent)
        print(f'Runner: {type(runner).__name__}, parent {runner.parent.state}, legs {len(runner.parent.legs)}')

        body, status = self.engine.answer(intent)
        print(f'Answer: {status} {body["outcome"]} at {body["broker"]}, order {body["order_id"]}')
        print(f'Sent to the broker: {self.placement.sent}')
        self.engine.reply(intent, body, status)
        self.engine.acknowledge(entry_id)
        pushed = json.loads(self.cache.lists[intent['reply_key']][0])
        print(f'Pushed to the caller: {pushed["status"]} {pushed["body"]["outcome"]}')
        print(f'Unacknowledged entries: {self.cache.pending[INTENT_STREAM_KEY]}')

        print('Had the engine stopped before acknowledging, it would read the intent again:')
        started = self.engine.started_parent_id(intent)
        print(f'Already started the parent it answered with: {started == body["parent_id"]}')
        again_body, again_status = self.engine.answer(intent)
        print(f'Second answer: {again_status} {again_body["error"]}')
        self.engine.reply(intent, again_body, again_status)
        stored = json.loads(self.cache.strings[ANSWER_KEY_PREFIX + intent['intent_id']])
        print(f'Stored answer is still: {stored["status"]} {stored["body"]["outcome"]}')
        print(f'Sent to the broker: {self.placement.sent}')
        print(f'Placed {self.engine.placed}, repeated {self.engine.repeated}')
        print(f'Answer kept for {self.cache.expiries[intent["reply_key"]]} seconds; still in time: {time.time() < self.engine.expiry_moment(intent)}')


if __name__ == '__main__':
    AnsweringOneIntentByHandExample().run()
