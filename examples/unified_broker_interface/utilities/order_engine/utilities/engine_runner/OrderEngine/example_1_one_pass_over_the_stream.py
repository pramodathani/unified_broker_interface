"""Runs the order engine's loop over a stream holding four intents, then stops it and prints what each caller was answered.

The REST API writes every order it accepts to the Redis stream `unified:orders:intents` and waits on a reply list for the answer. `OrderEngine.run` reads that stream through its own consumer group, places each order, pushes the answer and acknowledges the entry. `streams` names the streams it reads and `ensure_group` creates its consumer group on each, which is harmless to call again.

The four entries are a market buy that the broker accepts, an order whose caller stopped waiting ten minutes ago, an order naming a type the engine does not run, and an entry that is not an intent at all. The engine places the first, answers the second and third with a refusal without calling a broker, and acknowledges the fourth unplaced, so nothing is left for the next start to read again.

Everything around the engine is a stand-in, so nothing leaves the machine. Redis is the in-memory `FakeEngineStoreRedis` from `test_runs/redis_stand_ins.py`, and the stop event is `OnePassStop` from `test_runs/engine_stand_ins.py`, which lets the loop make three passes and then stop instead of blocking for ever. The placement is a small class defined here that always chooses Zerodha and accepts every order; the lock and the logger are small classes too, and the logger prints the engine's closing summary. The event log is `RecordingEventLog`, which keeps rows in a list instead of PostgreSQL. Each parent gets a random id, so the program prints `<parent id>` in its place, rounds the lateness to whole seconds, and cuts the list of every order type the engine runs down to `...`.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_runner/OrderEngine/example_1_one_pass_over_the_stream.py
"""

import json

from test_runs.engine_stand_ins import (
    OnePassStop,
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


class StandInLock:
    """Stands in for the engine lock, which this process always keeps."""

    def refresh(self):
        """Keeps the lock.

        Returns:
            bool: Always True.
        """
        return True


class PrintingLogger:
    """A stand-in logger that prints informational lines and counts the rest.

    Attributes:
        warnings (int): How many warnings were logged.
        errors (int): How many errors were logged.
    """

    def __init__(self):
        """Builds the logger with nothing counted.

        Returns:
            None: This method returns nothing.
        """
        self.warnings = 0
        self.errors = 0

    def info(self, message):
        """Prints an informational line.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'[info] {message}')

    def warning(self, message):
        """Counts a warning, whose text carries timings and random ids.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        del message
        self.warnings = self.warnings + 1

    def error(self, message):
        """Counts an error.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        del message
        self.errors = self.errors + 1

    def exception(self, message):
        """Counts an error logged while handling an exception.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        del message
        self.errors = self.errors + 1


class OnePassOverTheStreamExample:
    """Writes four entries to the intent stream, runs the engine over them and prints the answers.

    Attributes:
        cache (FakeEngineStoreRedis): The stand-in Redis.
        placement (StandInPlacement): The stand-in placement.
        logger (PrintingLogger): The stand-in logger.
        engine (OrderEngine): The engine being shown.
        reply_keys (list): The reply list of each intent, in the order they were written.
    """

    def __init__(self):
        """Builds the engine over the stand-ins.

        Returns:
            None: This method returns nothing.
        """
        self.cache = FakeEngineStoreRedis()
        self.placement = StandInPlacement()
        self.logger = PrintingLogger()
        self.engine = OrderEngine(
            self.cache,
            self.placement,
            StandInLock(),
            self.logger,
            30.0,
            300,
            RecordingEventLog(),
            ParentStore(self.cache),
        )
        self.reply_keys = []

    def write_intent(self, name, body, minutes_overdue=0):
        """Writes one intent to the stream, as the REST API does.

        Args:
            name (str): A short name, which becomes the intent's id.
            body (dict): The caller's order.
            minutes_overdue (int): How many minutes ago the caller stopped waiting, or 0 for a caller still waiting.

        Returns:
            None: This method returns nothing.
        """
        intent = OrderIntent(body, INSTRUMENT_ID, 5.0)
        intent.intent_id = name
        intent.reply_key = f'unified:orders:intents:result:{name}'
        document = intent.document()
        if minutes_overdue:
            document['deadline_at'] = intent.created_at - minutes_overdue * 60
        self.cache.xadd(INTENT_STREAM_KEY, {
            INTENT_STREAM_FIELD: json.dumps(document),
        })
        self.reply_keys.append(intent.reply_key)

    def market_buy(self, **changes):
        """A market buy of ten RELIANCE shares, with fields changed.

        Args:
            **changes: Fields to add or replace.

        Returns:
            dict: The body.
        """
        body = {
            'instrument_id': INSTRUMENT_ID,
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 10,
        }
        body.update(changes)
        return body

    def shown(self, answer_text):
        """One pushed answer, with the random parent id, the exact lateness and the long list of known types shortened.

        Args:
            answer_text (str): The answer as the engine pushed it.

        Returns:
            dict: The answer.
        """
        answer = json.loads(answer_text)
        body = answer['body']
        if 'parent_id' in body:
            body['parent_id'] = '<parent id>'
        if 'expired_seconds' in body:
            body['expired_seconds'] = round(body['expired_seconds'])
        error = body.get('error') or ''
        if '; it runs ' in error:
            body['error'] = error.split('; it runs ')[0] + '; it runs ...'
        return answer

    def run(self):
        """Writes the entries, runs three passes of the loop and prints each answer.

        Returns:
            None: This method returns nothing.
        """
        self.write_intent('buy', self.market_buy())
        self.write_intent('late', self.market_buy(), minutes_overdue=10)
        self.write_intent('unknown_type', self.market_buy(synthetic={
            'type': 'teleport',
        }))
        self.cache.xadd(INTENT_STREAM_KEY, {
            INTENT_STREAM_FIELD: 'this is not an intent',
        })

        print(f'Streams read: {self.engine.streams()}')
        self.engine.ensure_group()
        self.engine.ensure_group()
        print(f'Consumer groups: {sorted(self.cache.groups[INTENT_STREAM_KEY])}')

        exit_code = self.engine.run(OnePassStop(3))
        print(f'Exit code: {exit_code}')
        print(f'Sent to the broker: {self.placement.sent}')
        for reply_key in self.reply_keys:
            answer = self.shown(self.cache.lists[reply_key][0])
            print(f'{reply_key.rsplit(":", 1)[1]}: {answer["status"]} {answer["body"]}')
        print(f'Unacknowledged entries: {self.cache.pending[INTENT_STREAM_KEY]}')
        print(f'Warnings: {self.logger.warnings}, errors: {self.logger.errors}')


if __name__ == '__main__':
    OnePassOverTheStreamExample().run()
