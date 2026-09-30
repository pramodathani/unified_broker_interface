"""Shows how the engine hands work to the worker that owns each parent when it runs with worker lanes.

With lanes, the engine's own thread only reads the streams and hands work out; worker threads place orders and own the parents they create. `take_intent` answers an intent that is too old, or was already started, before a broker is chosen for it, so it takes nobody's turn. Otherwise it asks the placement which broker the first leg would go to, asks the router for a worker in that broker's lane, and submits `place_on_worker`, which makes the order's legs go to that broker while the order type runs and records the worker as the parent's owner.

Every later piece of work about a parent goes to its owner through the router: `take_update` routes a broker's order update to `apply_update` (and acknowledges at once an update no parent owns), `take_early_updates` routes each held update whose order is now known to `apply_replayed_update`, and `reconcile_books` routes each change found in the polled order books to `apply_reconciled_update`. `roll_day` waits until no worker is busy before it rebuilds the parent caches, and skips the rebuild when the workers stay busy.

The router and its worker are small stand-in classes defined here that run each piece of work at once on the calling thread and print where it went, so the output has a fixed order; the real `ParentRouter` runs a thread per worker. The placement, follower, reconciler and day roll are stand-ins too, and Redis is the in-memory `FakeEngineStoreRedis` from `test_runs/redis_stand_ins.py`. Nothing reaches a broker.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/engine_runner/OrderEngine/example_6_worker_lanes.py
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
from unified_broker_interface.utilities.order_engine.utilities.order_update_follower import (
    ORDER_UPDATES_STREAM_KEY,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
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


class LanePlacement(StandInPlacement):
    """The stand-in placement, widened with the broker assignment intake makes for a lane.

    Attributes:
        assigned_broker (str | None): The broker this thread's legs must go to, or None to choose Zerodha.
    """

    def __init__(self):
        """Builds the placement with no assignment.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.assigned_broker = None

    def assign_broker(self, intent):
        """Chooses the broker the intent's first leg would go to, without sending anything.

        Args:
            intent (dict): The intent document.

        Returns:
            tuple: The broker's name (str) and the brokers passed over (list).
        """
        del intent
        return 'zerodha', []

    def use_assignment(self, broker_name, skipped):
        """Makes this thread's legs go to one broker until `clear_assignment`.

        Args:
            broker_name (str | None): The broker.
            skipped (list): The brokers passed over, unused by the stand-in.

        Returns:
            None: This method returns nothing.
        """
        del skipped
        self.assigned_broker = broker_name

    def clear_assignment(self):
        """Forgets the assignment.

        Returns:
            None: This method returns nothing.
        """
        self.assigned_broker = None

    def prepare(self, order, instrument_id, broker_name=None):
        """Builds the request for the assigned broker, or Zerodha when there is none.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument_id (str): The instrument.
            broker_name (str | None): The broker the order must go to, or None for the assigned one.

        Returns:
            StandInPreparedPlacement: The prepared order.
        """
        return super().prepare(
            order,
            instrument_id,
            broker_name or self.assigned_broker,
        )


class InlineWorker:
    """Stands in for one worker thread, running what it is given at once.

    Attributes:
        name (str): The worker's name, its lane and number.
    """

    def __init__(self, name):
        """Builds the worker.

        Args:
            name (str): The worker's name.

        Returns:
            None: This method returns nothing.
        """
        self.name = name

    def submit(self, function, arguments):
        """Runs one piece of work now, on the calling thread.

        Args:
            function (callable): The work.
            arguments (tuple): Its arguments.

        Returns:
            None: This method returns nothing.
        """
        print(f'  {self.name} runs {function.__name__}')
        function(*arguments)


class InlineRouter:
    """Stands in for the parent router, with one inline worker per broker lane.

    Attributes:
        workers (dict): Each lane's worker, by broker name.
        owners (dict): Each parent's owning worker's name, by parent id.
        idle (bool): What `wait_until_idle` answers.
    """

    def __init__(self):
        """Builds the router with no workers yet.

        Returns:
            None: This method returns nothing.
        """
        self.workers = {}
        self.owners = {}
        self.idle = True

    def worker_for_new_intent(self, broker_name):
        """The worker in a broker's lane that takes a new parent.

        Args:
            broker_name (str): The broker.

        Returns:
            InlineWorker: The worker.
        """
        if broker_name not in self.workers:
            self.workers[broker_name] = InlineWorker(f'{broker_name}-1')
        return self.workers[broker_name]

    def register(self, parent_order_id, worker):
        """Records which worker owns a parent.

        Args:
            parent_order_id (str): The parent's id.
            worker (InlineWorker): Its owner.

        Returns:
            None: This method returns nothing.
        """
        self.owners[parent_order_id] = worker.name

    def route(self, parent_order_id, broker_name, function, arguments):
        """Hands one piece of work to the worker that owns a parent.

        Args:
            parent_order_id (str | None): The parent's id.
            broker_name (str | None): The parent's broker, whose lane takes a parent nobody owns.
            function (callable): The work.
            arguments (tuple): Its arguments.

        Returns:
            None: This method returns nothing.
        """
        print(f'  routed for parent {parent_order_id} at {broker_name}:')
        self.worker_for_new_intent(broker_name or 'zerodha').submit(function, arguments)

    def wait_until_idle(self, stop, seconds):
        """Whether every worker is idle.

        Args:
            stop (threading.Event | None): Set when the engine is stopping, unused by the stand-in.
            seconds (float): How long to wait, unused by the stand-in.

        Returns:
            bool: The configured answer.
        """
        del stop, seconds
        return self.idle

    def forget_owners(self):
        """Forgets every parent's owner, after the caches are rebuilt.

        Returns:
            None: This method returns nothing.
        """
        self.owners = {}


class LaneFollower:
    """Stands in for the order update follower, owning one parent.

    Attributes:
        parent (ParentOrder): The one parent whose updates are followed.
        waiting (list): Held updates whose order is now known, as `(parent_order_id, broker, fields)`.
        replayed (int): How many held updates were applied.
    """

    def __init__(self, parent):
        """Builds the follower.

        Args:
            parent (ParentOrder): The parent it follows.

        Returns:
            None: This method returns nothing.
        """
        self.parent = parent
        self.waiting = []
        self.replayed = 0

    def owning_parent(self, fields):
        """The parent and broker an update belongs to.

        Args:
            fields (dict): The stream entry's fields.

        Returns:
            tuple: The parent's id and broker, or `(None, None)` when no parent owns it.
        """
        if fields['order_id'] == '260930000050':
            return self.parent.parent_order_id, 'zerodha'
        return None, None

    def follow(self, fields):
        """Applies one update to the parent's state.

        Args:
            fields (dict): The stream entry's fields, with `parent_state`.

        Returns:
            ParentOrder: The changed parent.
        """
        self.parent.state = fields['parent_state']
        return self.parent

    def take_known_early_updates(self):
        """The held updates whose order is now known, taken out of the holding.

        Returns:
            list: The updates, as `(parent_order_id, broker, fields)`.
        """
        taken = self.waiting
        self.waiting = []
        return taken

    def count_replayed(self):
        """Counts one held update applied.

        Returns:
            None: This method returns nothing.
        """
        self.replayed = self.replayed + 1


class ListReconciler:
    """Stands in for the book reconciler, answering with a fixed list of changes.

    Attributes:
        missed (list): The changes, as `(parent_order_id, broker, fields)`.
    """

    def __init__(self, missed):
        """Builds the reconciler.

        Args:
            missed (list): The changes.

        Returns:
            None: This method returns nothing.
        """
        self.missed = missed

    def missed_updates(self):
        """The changes the polled books show and no socket delivered.

        Returns:
            list: The changes.
        """
        return list(self.missed)


class CountingDayRoll:
    """Stands in for the day roll, counting rebuilds.

    Attributes:
        rolls (int): How many times the caches were rebuilt.
    """

    def __init__(self):
        """Builds the day roll.

        Returns:
            None: This method returns nothing.
        """
        self.rolls = 0

    def roll(self):
        """Counts one rebuild.

        Returns:
            None: This method returns nothing.
        """
        self.rolls = self.rolls + 1


class WorkerLanesExample:
    """Hands intents, updates and book changes to lane workers and prints where each went.

    Attributes:
        cache (FakeEngineStoreRedis): The stand-in Redis.
        placement (LanePlacement): The stand-in placement.
        router (InlineRouter): The stand-in router.
        follower (LaneFollower): The stand-in follower.
        day_roll (CountingDayRoll): The stand-in day roll.
        engine (OrderEngine): The engine being shown.
    """

    def __init__(self):
        """Builds the engine with lanes over the stand-ins.

        Returns:
            None: This method returns nothing.
        """
        logger = logging.getLogger('example')
        logger.setLevel(logging.CRITICAL)
        self.cache = FakeEngineStoreRedis()
        self.placement = LanePlacement()
        self.router = InlineRouter()
        followed = ParentOrder('bracket-7')
        followed.synthetic_type = 'bracket'
        followed.state = 'working'
        self.follower = LaneFollower(followed)
        self.day_roll = CountingDayRoll()
        self.engine = OrderEngine(
            self.cache,
            self.placement,
            None,
            logger,
            30.0,
            300,
            RecordingEventLog(),
            ParentStore(self.cache),
            self.follower,
            day_roll=self.day_roll,
            router=self.router,
            reconciler=ListReconciler([
                (
                    'bracket-7',
                    'zerodha',
                    {
                        'order_id': '260930000050',
                        'parent_state': 'completed',
                    },
                ),
            ]),
        )
        self.engine.ensure_group()

    def write(self, name, minutes_overdue=0):
        """Writes one market buy intent to the stream and reads it back.

        Args:
            name (str): A short name, which becomes the intent's id.
            minutes_overdue (int): How many minutes ago the caller stopped waiting, or 0 for a caller still waiting.

        Returns:
            tuple: The entry's id (str), its fields (dict) and the intent document (dict).
        """
        intent = OrderIntent(
            {
                'instrument_id': INSTRUMENT_ID,
                'transaction_type': 'SELL',
                'product': 'MIS',
                'order_type': 'MARKET',
                'quantity': 3,
            },
            INSTRUMENT_ID,
            5.0,
        )
        intent.intent_id = name
        intent.reply_key = f'unified:orders:intents:result:{name}'
        document = intent.document()
        if minutes_overdue:
            document['deadline_at'] = intent.created_at - minutes_overdue * 60
        self.cache.xadd(INTENT_STREAM_KEY, {
            INTENT_STREAM_FIELD: json.dumps(document),
        })
        _, entry_id, fields = self.engine.read(False)[-1]
        return entry_id, fields, document

    def answer_status(self, name):
        """The HTTP status pushed for one intent.

        Args:
            name (str): The intent's id.

        Returns:
            int: The status.
        """
        return json.loads(self.cache.lists[f'unified:orders:intents:result:{name}'][0])['status']

    def run(self):
        """Hands out each kind of work and prints where it went.

        Returns:
            None: This method returns nothing.
        """
        print('A new intent:')
        entry_id, fields, _ = self.write('fresh')
        self.engine.take_intent(entry_id, fields)
        print(f'  answered {self.answer_status("fresh")}, parents owned: {list(self.router.owners.values())}')

        print('An intent whose caller stopped waiting:')
        entry_id, fields, _ = self.write('late', minutes_overdue=10)
        self.engine.take_intent(entry_id, fields)
        print(f'  answered {self.answer_status("late")} on intake, workers: {sorted(self.router.workers)}')

        print('An intent handed straight to a worker in the Dhan lane:')
        entry_id, fields, intent = self.write('to_dhan')
        worker = self.router.worker_for_new_intent('dhan')
        self.engine.place_on_worker(entry_id, intent, 'dhan', [], worker)
        print(f'  answered {self.answer_status("to_dhan")}, sent: {self.placement.sent}')
        print(f'  assignment afterwards: {self.placement.assigned_broker}')

        print('Order updates:')
        owned = {
            'order_id': '260930000050',
            'parent_state': 'protecting',
        }
        entry_id = self.cache.xadd(ORDER_UPDATES_STREAM_KEY, owned)
        self.engine.take_update(entry_id, owned)
        stranger = {
            'order_id': '111111111111',
            'parent_state': 'completed',
        }
        entry_id = self.cache.xadd(ORDER_UPDATES_STREAM_KEY, stranger)
        self.engine.take_update(entry_id, stranger)
        print(f'  bracket-7 is {self.follower.parent.state}; the stranger was acknowledged without a worker')

        print('A held update whose order is now known:')
        self.follower.waiting.append((
            'bracket-7',
            'zerodha',
            {
                'order_id': '260930000050',
                'parent_state': 'protecting',
            },
        ))
        self.engine.take_early_updates()
        print(f'  replayed: {self.follower.replayed}')

        print('A change found in the polled order book:')
        self.engine.reconcile_books()
        print(f'  bracket-7 is {self.follower.parent.state}')

        print('The day rolls over:')
        self.engine.roll_day(None)
        print(f'  rolls {self.day_roll.rolls}, owners remembered: {len(self.router.owners)}')
        self.router.idle = False
        self.engine.roll_day(None)
        print(f'  with busy workers: rolls {self.day_roll.rolls}')


if __name__ == '__main__':
    WorkerLanesExample().run()
