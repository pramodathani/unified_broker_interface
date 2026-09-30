"""Places two orders through the engine, cancels one of them with a caller's command, and then halts every parent still open.

A caller's change to an order the engine owns arrives on the same stream as new orders, as an intent that carries a `command`. `take_command` runs it on the thread that owns the parent, which here is the engine's own thread because the program uses no worker lanes, and `finish_command` runs the command, pushes its answer and acknowledges it. `DELETE /api/orders/parents` sends `cancel_parent`, which cancels every leg still resting at its broker and then the parent itself.

`POST /api/orders/flatten` first sends `halt`, which `halt_every_parent` handles: every open parent is stopped from placing, moving or cancelling anything more, and the answer says how many there were. A second halt finds none left. A command the engine does not know is answered 400.

Redis is the in-memory `FakeEngineStoreRedis` from `test_runs/redis_stand_ins.py` and the event log is `RecordingEventLog` from `test_runs/engine_stand_ins.py`. The placement is a small class defined here that sends every order to Zerodha, numbers the order ids it hands back, and accepts every cancel, so nothing reaches a broker. Each parent gets a random id, so the program prints `first` and `second` in place of the two ids.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_runner/OrderEngine/example_4_cancelling_and_halting_parents.py
"""

import json
import logging

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
from unified_broker_interface.utilities.order_engine.utilities.parent_commands import (
    CANCEL_PARENT,
    HALT_EVERY_PARENT,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    ParentStore,
)

INSTRUMENT_ID = '11111111-1111-5111-8111-000000000001'


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
    """An order given to Zerodha, but not yet sent.

    Attributes:
        broker_name (str): The chosen broker.
        broker_request (StandInBrokerRequest): The request built for it.
        identifier_sent (str): The symbol the request names the instrument by.
    """

    def __init__(self, broker_request):
        """Builds the prepared placement.

        Args:
            broker_request (StandInBrokerRequest): The request built for it.

        Returns:
            None: This method returns nothing.
        """
        self.broker_name = 'zerodha'
        self.broker_request = broker_request
        self.identifier_sent = 'RELIANCE'


class StandInCancelAnswer:
    """What a broker said to a cancel, reduced to what the engine reads.

    Attributes:
        outcome (str): Always `accepted`.
        status_message (str | None): Always None.
        response_body (dict): The broker's body.
    """

    def __init__(self, broker_order_id):
        """Builds an accepted answer.

        Args:
            broker_order_id (str): The order that was cancelled.

        Returns:
            None: This method returns nothing.
        """
        self.outcome = 'accepted'
        self.status_message = None
        self.response_body = {
            'status': 'success',
            'data': {
                'order_id': broker_order_id,
            },
        }


class StandInPlacement:
    """Stands in for the engine's placement: sends to Zerodha, numbers the order ids and accepts every cancel.

    Attributes:
        next_number (int): The number the next broker order id is made from.
        cancelled (list): Every order a cancel was sent for, as `(broker, order_id)`.
    """

    def __init__(self):
        """Builds the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.next_number = 1
        self.cancelled = []

    def prepare(self, order, instrument_id, broker_name=None):
        """Builds the request for Zerodha, without sending it.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument_id (str): The instrument, unused by the stand-in.
            broker_name (str | None): The broker the order must go to, unused by the stand-in.

        Returns:
            StandInPreparedPlacement: The prepared order.
        """
        del instrument_id, broker_name
        return StandInPreparedPlacement(StandInBrokerRequest(order.tag))

    def send(self, prepared_placement, started_at):
        """Sends the order, which the stand-in broker accepts with the next order id.

        Args:
            prepared_placement (StandInPreparedPlacement): The prepared order.
            started_at (float): When the engine took the intent, unused.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        del started_at
        order_id = f'2609300000{self.next_number:02d}'
        self.next_number = self.next_number + 1
        return {
            'broker': prepared_placement.broker_name,
            'outcome': 'accepted',
            'order_id': order_id,
        }, 200

    def cancel(self, broker_name, broker_order_id):
        """Cancels one order, which the stand-in broker accepts.

        Args:
            broker_name (str): The broker.
            broker_order_id (str): The broker's order id.

        Returns:
            StandInCancelAnswer: The accepted answer.
        """
        self.cancelled.append((broker_name, broker_order_id))
        return StandInCancelAnswer(broker_order_id)


class CancellingAndHaltingParentsExample:
    """Places two orders, cancels the first by command and halts what is left.

    Attributes:
        cache (FakeEngineStoreRedis): The stand-in Redis.
        placement (StandInPlacement): The stand-in placement.
        engine (OrderEngine): The engine being shown.
        names (dict): A readable name for each parent id.
    """

    def __init__(self):
        """Builds the engine over the stand-ins.

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
        self.engine.ensure_group()
        self.names = {}

    def write(self, name, body, command=None):
        """Writes one intent to the stream and reads it back, as the engine's loop would.

        Args:
            name (str): A short name, which becomes the intent's id.
            body (dict): The order, or the command's arguments.
            command (str | None): The command, or None for an order to place.

        Returns:
            tuple: The entry's id (str), its fields (dict) and the intent document (dict).
        """
        intent = OrderIntent(body, INSTRUMENT_ID, 5.0, command=command)
        intent.intent_id = name
        intent.reply_key = f'unified:orders:intents:result:{name}'
        document = intent.document()
        self.cache.xadd(INTENT_STREAM_KEY, {
            INTENT_STREAM_FIELD: json.dumps(document),
        })
        _, entry_id, fields = self.engine.read(False)[0]
        return entry_id, fields, document

    def answer_for(self, name):
        """The answer pushed for one intent, with parent ids replaced by readable names.

        Args:
            name (str): The intent's id.

        Returns:
            tuple: The HTTP status (int) and the body (dict).
        """
        answer = json.loads(self.cache.lists[f'unified:orders:intents:result:{name}'][0])
        body = answer['body']
        if body.get('parent_id') in self.names:
            body['parent_id'] = self.names[body['parent_id']]
        for leg in body.get('cancelled_legs') or []:
            leg['leg_id'] = self.names[leg['leg_id'].split(':')[0]] + ':' + leg['leg_id'].split(':')[1]
        return answer['status'], body

    def place(self, name):
        """Places one market buy through `take_intent` and remembers its parent's name.

        Args:
            name (str): The intent's id, used as the parent's readable name.

        Returns:
            str: The parent's id.
        """
        entry_id, fields, _ = self.write(name, {
            'instrument_id': INSTRUMENT_ID,
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 10,
        })
        self.engine.take_intent(entry_id, fields)
        answer = json.loads(self.cache.lists[f'unified:orders:intents:result:{name}'][0])
        parent_order_id = answer['body']['parent_id']
        self.names[parent_order_id] = name
        return parent_order_id

    def run(self):
        """Places the orders, runs the commands and prints each answer.

        Returns:
            None: This method returns nothing.
        """
        first = self.place('first')
        self.place('second')
        print(f'Open parents: {len(self.engine.parent_store.open_parent_ids())}')

        entry_id, _, intent = self.write('cancel_first', {
            'parent_id': first,
        }, command=CANCEL_PARENT)
        self.engine.take_command(entry_id, intent)
        status, body = self.answer_for('cancel_first')
        print(f'cancel_parent: {status} {body}')
        print(f'Cancels sent: {self.placement.cancelled}')

        entry_id, _, intent = self.write('pause_first', {
            'parent_id': first,
        }, command='pause')
        self.engine.finish_command(entry_id, intent)
        status, body = self.answer_for('pause_first')
        print(f'pause: {status} {body}')

        entry_id, _, intent = self.write('halt', {}, command=HALT_EVERY_PARENT)
        self.engine.halt_every_parent(entry_id, intent)
        status, body = self.answer_for('halt')
        print(f'halt: {status} {body}')
        for parent_order_id in self.names:
            parent = self.engine.parent_store.parent(parent_order_id)
            print(f'{self.names[parent_order_id]} is now {parent["state"]}: {parent["last_error"]}')

        entry_id, _, intent = self.write('halt_again', {}, command=HALT_EVERY_PARENT)
        self.engine.take_command(entry_id, intent)
        status, body = self.answer_for('halt_again')
        print(f'halt again: {status} {body}')
        print(f'Unacknowledged entries: {self.cache.pending[INTENT_STREAM_KEY]}')


if __name__ == '__main__':
    CancellingAndHaltingParentsExample().run()
