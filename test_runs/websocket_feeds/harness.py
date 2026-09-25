"""The stand-ins every websocket feed case is run against.

A case builds a socket the way its script does, hands it a `ScenarioContext`, and lets the socket run its own reconnect loop against a scripted list of connections.
Everything the socket does to the outside world goes into one ordered event log, which is what the suite records and compares.
"""

import base64
import datetime
import hashlib
import importlib.machinery
import importlib.util
import logging
import pathlib
import sys
import time
import types
from zoneinfo import ZoneInfo

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
INDIA = ZoneInfo('Asia/Kolkata')
FROZEN_MOMENT = datetime.datetime(2026, 9, 25, 10, 15, 30, 123456, tzinfo=INDIA)


class EventLog:
    """The ordered record of everything one scenario did.

    Attributes:
        events (list): One list per event, starting with the event's kind.
    """

    def __init__(self):
        """Starts an empty log.

        Returns:
            None: This method returns nothing.
        """
        self.events = []

    def add(self, kind, *values):
        """Appends one event.

        Args:
            kind (str): What happened, such as `redis`, `send` or `log`.
            *values: The event's details, each made safe for JSON.

        Returns:
            None: This method returns nothing.
        """
        event = [kind]
        for value in values:
            event.append(self.safe(value))
        self.events.append(event)

    def safe(self, value):
        """Turns a value into something JSON can hold without losing what it was.

        Bytes become a tagged base64 string, tuples become lists and dictionaries become sorted lists of pairs, so the recording shows the same thing on every run.

        Args:
            value (object): The value to convert.

        Returns:
            object: The converted value.
        """
        if isinstance(value, (bytes, bytearray)):
            return {
                'bytes': base64.b64encode(bytes(value)).decode('ascii'),
            }
        if isinstance(value, dict):
            pairs = []
            for key, item in value.items():
                pairs.append([self.safe(key), self.safe(item)])
            return pairs
        if isinstance(value, (list, tuple)):
            converted = []
            for item in value:
                converted.append(self.safe(item))
            return converted
        if isinstance(value, float) or isinstance(value, int) or value is None:
            return value
        if isinstance(value, str):
            return value
        return repr(value)


class RecordingPipeline:
    """A Redis pipeline that keeps its queued commands and records them as one event when executed.

    Attributes:
        redis (RecordingRedis): The client the pipeline came from.
        transaction (bool): Whether the pipeline was opened as a transaction.
        commands (list): The queued commands.
    """

    def __init__(self, redis, transaction):
        """Opens an empty pipeline.

        Args:
            redis (RecordingRedis): The client the pipeline came from.
            transaction (bool): Whether the pipeline was opened as a transaction.

        Returns:
            None: This method returns nothing.
        """
        self.redis = redis
        self.transaction = transaction
        self.commands = []

    def hset(self, key, field=None, value=None, mapping=None):
        """Queues an HSET.

        Args:
            key (str): The hash.
            field (str | None): A single field to set.
            value (str | None): The single field's value.
            mapping (dict | None): Several fields to set.

        Returns:
            RecordingPipeline: This pipeline.
        """
        self.commands.append(self.redis.hset_command(key, field, value, mapping))
        return self

    def xadd(self, key, fields, maxlen=None, approximate=True):
        """Queues an XADD.

        Args:
            key (str): The stream.
            fields (dict): The entry's fields.
            maxlen (int | None): The cap on the stream's length.
            approximate (bool): Whether the cap is approximate.

        Returns:
            RecordingPipeline: This pipeline.
        """
        self.commands.append(
            [
                'xadd',
                key,
                fields,
                maxlen,
                approximate,
            ]
        )
        return self

    def delete(self, key):
        """Queues a DEL.

        Args:
            key (str): The key to delete.

        Returns:
            RecordingPipeline: This pipeline.
        """
        self.commands.append(
            [
                'delete',
                key,
            ]
        )
        return self

    def execute(self):
        """Records every queued command as one round trip.

        Returns:
            list: One placeholder answer per command.
        """
        self.redis.event_log.add('pipeline', self.transaction, self.commands)
        answers = []
        for _ in self.commands:
            answers.append(1)
        self.commands = []
        return answers


class RecordedScript:
    """A registered Lua script whose calls are recorded rather than run.

    Attributes:
        redis (RecordingRedis): The client the script was registered on.
        digest (str): The start of the SHA-1 of the script's text, so a changed script shows in the recording.
    """

    def __init__(self, redis, digest):
        """Keeps what the calls are recorded against.

        Args:
            redis (RecordingRedis): The client the script was registered on.
            digest (str): The start of the SHA-1 of the script's text.

        Returns:
            None: This method returns nothing.
        """
        self.redis = redis
        self.digest = digest

    def __call__(self, keys=None, args=None):
        """Records one call of the script.

        Args:
            keys (list | None): The script's KEYS.
            args (list | None): The script's ARGV.

        Returns:
            int: A placeholder answer.
        """
        self.redis.event_log.add('script', self.digest, keys or [], args or [])
        return 1


class RecordingRedis:
    """An in-memory stand-in for the parts of a Redis client the feeds use.

    Reads answer from seeded state and are recorded; writes are recorded and not applied, because no feed reads back what it wrote.

    Attributes:
        event_log (EventLog): Where commands are recorded.
        strings (dict): String keys to their values.
        hashes (dict): Hash keys to dictionaries of fields.
        sets (dict): Set keys to sets of members.
    """

    def __init__(self, event_log):
        """Starts with no keys.

        Args:
            event_log (EventLog): Where commands are recorded.

        Returns:
            None: This method returns nothing.
        """
        self.event_log = event_log
        self.strings = {}
        self.hashes = {}
        self.sets = {}

    def hset_command(self, key, field, value, mapping):
        """Builds the recorded form of an HSET.

        Args:
            key (str): The hash.
            field (str | None): A single field to set.
            value (str | None): The single field's value.
            mapping (dict | None): Several fields to set.

        Returns:
            list: The command as recorded.
        """
        return [
            'hset',
            key,
            field,
            value,
            mapping,
        ]

    def pipeline(self, transaction=True):
        """Opens a pipeline.

        Args:
            transaction (bool): Whether the pipeline is a transaction.

        Returns:
            RecordingPipeline: The new pipeline.
        """
        return RecordingPipeline(self, transaction)

    def register_script(self, script_text):
        """Registers a Lua script, recording which one.

        Args:
            script_text (str): The script's source.

        Returns:
            RecordedScript: A callable that records each call of the script.
        """
        digest = hashlib.sha1(script_text.encode('utf-8')).hexdigest()[:12]
        self.event_log.add('register_script', digest)
        return RecordedScript(self, digest)

    def hset(self, key, field=None, value=None, mapping=None):
        """Records an HSET sent on its own.

        Args:
            key (str): The hash.
            field (str | None): A single field to set.
            value (str | None): The single field's value.
            mapping (dict | None): Several fields to set.

        Returns:
            int: A placeholder answer.
        """
        self.event_log.add('redis', self.hset_command(key, field, value, mapping))
        return 1

    def delete(self, key):
        """Records a DEL sent on its own.

        Args:
            key (str): The key to delete.

        Returns:
            int: A placeholder answer.
        """
        self.event_log.add(
            'redis',
            [
                'delete',
                key,
            ],
        )
        return 1

    def get(self, key):
        """Answers a GET from the seeded strings.

        Args:
            key (str): The key to read.

        Returns:
            str | None: The seeded value, or None.
        """
        self.event_log.add(
            'redis',
            [
                'get',
                key,
            ],
        )
        return self.strings.get(key)

    def hget(self, key, field):
        """Answers an HGET from the seeded hashes.

        Args:
            key (str): The hash.
            field (str): The field to read.

        Returns:
            str | None: The seeded value, or None.
        """
        self.event_log.add(
            'redis',
            [
                'hget',
                key,
                field,
            ],
        )
        return self.hashes.get(key, {}).get(field)

    def hmget(self, key, fields):
        """Answers an HMGET from the seeded hashes.

        Args:
            key (str): The hash.
            fields (list): The fields to read.

        Returns:
            list: The seeded value, or None, for each field in order.
        """
        field_list = list(fields)
        self.event_log.add(
            'redis',
            [
                'hmget',
                key,
                field_list,
            ],
        )
        values = []
        for field in field_list:
            values.append(self.hashes.get(key, {}).get(field))
        return values

    def hscan_iter(self, key, count=None):
        """Walks a seeded hash in insertion order.

        Args:
            key (str): The hash.
            count (int | None): The batch size a real client would ask for.

        Yields:
            tuple: Each field and its value.
        """
        self.event_log.add(
            'redis',
            [
                'hscan_iter',
                key,
                count,
            ],
        )
        for field, value in self.hashes.get(key, {}).items():
            yield field, value

    def smembers(self, key):
        """Answers an SMEMBERS from the seeded sets.

        Args:
            key (str): The set.

        Returns:
            set: The seeded members.
        """
        self.event_log.add(
            'redis',
            [
                'smembers',
                key,
            ],
        )
        return set(self.sets.get(key, set()))


class InstantEvent:
    """A stand-in for `threading.Event` whose waits return at once and are recorded.

    Attributes:
        event_log (EventLog): Where waits are recorded.
        flag (bool): Whether the event is set.
    """

    def __init__(self, event_log):
        """Starts unset.

        Args:
            event_log (EventLog): Where waits are recorded.

        Returns:
            None: This method returns nothing.
        """
        self.event_log = event_log
        self.flag = False

    def set(self):
        """Sets the event.

        Returns:
            None: This method returns nothing.
        """
        self.flag = True

    def clear(self):
        """Clears the event.

        Returns:
            None: This method returns nothing.
        """
        self.flag = False

    def is_set(self):
        """Says whether the event is set.

        Returns:
            bool: True once set.
        """
        return self.flag

    def wait(self, timeout=None):
        """Records a wait and returns at once.

        Args:
            timeout (float | None): How long the caller asked to wait.

        Returns:
            bool: Whether the event is set.
        """
        self.event_log.add('wait', timeout)
        return self.flag


class FakeWebsocketError(Exception):
    """A websocket failure as websocket-client reports it, optionally with the handshake's HTTP status.

    Attributes:
        status_code (int | None): The HTTP status the handshake was answered with.
    """

    def __init__(self, message, status_code=None):
        """Keeps the message and the status.

        Args:
            message (str): The error's text.
            status_code (int | None): The HTTP status the handshake was answered with.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(message)
        self.status_code = status_code


class ConnectionPlan:
    """The scripted connections a scenario plays, one list of steps per connection attempt.

    A step is a tuple whose first item says what happens:
    `('open',)` calls the socket's open handler,
    `('message', payload)` delivers a frame,
    `('error', error)` calls the error handler,
    `('close', status, reason)` calls the close handler,
    `('raise', error)` makes the connection attempt itself raise,
    and `('call', function)` runs something in the outside world, such as another process logging in.

    Attributes:
        connections (list): The connection attempts still to play.
        on_exhausted (callable | None): What to call when a connection is attempted after the last one, which is how a scenario ends.
    """

    def __init__(self, connections):
        """Keeps the scripted connections.

        Args:
            connections (list): One list of steps per connection attempt.

        Returns:
            None: This method returns nothing.
        """
        self.connections = list(connections)
        self.on_exhausted = None

    def next_connection(self):
        """Takes the next connection attempt's steps.

        Returns:
            list | None: The steps, or None when every scripted attempt has been played.
        """
        if not self.connections:
            return None
        return self.connections.pop(0)


class FakeWebsocketApplication:
    """A stand-in for `websocket.WebSocketApp` that plays one scripted connection per `run_forever`.

    Attributes:
        module (FakeWebsocketModule): The fake module that made it.
        url (str): The URL the socket connects to.
        callbacks (dict): The handlers the socket registered.
    """

    def __init__(self, module, url, keyword_arguments):
        """Keeps the URL and handlers and records the construction.

        Args:
            module (FakeWebsocketModule): The fake module that made it.
            url (str): The URL the socket connects to.
            keyword_arguments (dict): Everything else `WebSocketApp` was given.

        Returns:
            None: This method returns nothing.
        """
        self.module = module
        self.url = url
        self.callbacks = {}
        options = {}
        for name, value in keyword_arguments.items():
            if name.startswith('on_'):
                self.callbacks[name] = value
            else:
                options[name] = value
        self.module.event_log.add('connect', url, options)

    def run_forever(self, **keyword_arguments):
        """Plays the next scripted connection, then returns as a closed connection would.

        Args:
            **keyword_arguments: The options `run_forever` was given, such as ping intervals.

        Returns:
            None: This method returns nothing.
        """
        options = {}
        for name, value in keyword_arguments.items():
            if name == 'sslopt':
                options[name] = sorted(value)
            else:
                options[name] = value
        self.module.event_log.add('run_forever', options)
        steps = self.module.plan.next_connection()
        if steps is None:
            self.module.plan.on_exhausted()
            return
        for step in steps:
            self.play(step)

    def play(self, step):
        """Plays one step of a scripted connection.

        Args:
            step (tuple): The step, as described in `ConnectionPlan`.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: The step's error, for a `raise` step.
        """
        kind = step[0]
        if kind == 'open':
            self.callbacks['on_open'](self)
        elif kind == 'message':
            self.callbacks['on_message'](self, step[1])
        elif kind == 'error':
            self.callbacks['on_error'](self, step[1])
        elif kind == 'close':
            self.callbacks['on_close'](self, step[1], step[2])
        elif kind == 'raise':
            raise step[1]
        elif kind == 'call':
            step[1]()
        else:
            raise ValueError(f'Unknown connection step: {step!r}')

    def send(self, data, opcode=None):
        """Records a frame sent to the broker.

        Args:
            data (str | bytes): The frame.
            opcode (int | None): The websocket opcode, when one was given.

        Returns:
            None: This method returns nothing.
        """
        self.module.event_log.add('send', data, opcode)

    def close(self, **keyword_arguments):
        """Records that the socket closed its connection.

        Args:
            **keyword_arguments: Whatever `close` was given.

        Returns:
            None: This method returns nothing.
        """
        self.module.event_log.add('close_connection')


class FakeWebsocketModule(types.ModuleType):
    """A stand-in for the `websocket` package, placed in `sys.modules` while a scenario runs.

    Attributes:
        event_log (EventLog): Where connections and frames are recorded.
        plan (ConnectionPlan): The scripted connections.
    """

    WebSocketException = FakeWebsocketError
    WebSocketTimeoutException = TimeoutError

    def __init__(self, event_log, plan):
        """Keeps the log and the plan.

        Args:
            event_log (EventLog): Where connections and frames are recorded.
            plan (ConnectionPlan): The scripted connections.

        Returns:
            None: This method returns nothing.
        """
        super().__init__('websocket')
        self.event_log = event_log
        self.plan = plan

    def WebSocketApp(self, url, **keyword_arguments):  # pylint: disable=invalid-name
        """Builds a fake application, as `websocket.WebSocketApp(...)` would.

        Args:
            url (str): The URL to connect to.
            **keyword_arguments: The handlers and options.

        Returns:
            FakeWebsocketApplication: The fake application.
        """
        return FakeWebsocketApplication(self, url, keyword_arguments)


class CapturingHandler(logging.Handler):
    """A logging handler that puts each record into the event log.

    Attributes:
        event_log (EventLog): Where log lines are recorded.
    """

    def __init__(self, event_log):
        """Keeps the log.

        Args:
            event_log (EventLog): Where log lines are recorded.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(level=logging.DEBUG)
        self.event_log = event_log

    def emit(self, record):
        """Records one log line.

        Args:
            record (logging.LogRecord): The record.

        Returns:
            None: This method returns nothing.
        """
        self.event_log.add('log', record.levelname, record.getMessage())


class FrozenDatetime(datetime.datetime):
    """A `datetime` whose `now()` is always `FROZEN_MOMENT`."""

    @classmethod
    def now(cls, tz=None):
        """Answers the frozen moment, in the zone asked for or as a naive India wall clock time.

        Args:
            tz (datetime.tzinfo | None): The zone to express the moment in.

        Returns:
            datetime.datetime: The frozen moment.
        """
        moment = FROZEN_MOMENT
        if tz is None:
            moment = moment.replace(tzinfo=None)
        else:
            moment = moment.astimezone(tz)
        return cls(
            moment.year,
            moment.month,
            moment.day,
            moment.hour,
            moment.minute,
            moment.second,
            moment.microsecond,
            tzinfo=moment.tzinfo,
        )


class LoginLedger:
    """The broker's login state as a scenario sees it: the token in force and how many logins happened.

    Attributes:
        event_log (EventLog): Where logins are recorded.
        login_count (int): How many logins have happened.
        current_token (str | None): The token in force now.
        failing_logins (set): The login numbers that fail.
    """

    def __init__(self, event_log):
        """Starts with no login.

        Args:
            event_log (EventLog): Where logins are recorded.

        Returns:
            None: This method returns nothing.
        """
        self.event_log = event_log
        self.login_count = 0
        self.current_token = None
        self.failing_logins = set()

    def log_in(self):
        """Performs one login, which issues a new token unless this login is scripted to fail.

        Returns:
            str: The new token.

        Raises:
            RuntimeError: When this login is scripted to fail.
        """
        self.login_count = self.login_count + 1
        if self.login_count in self.failing_logins:
            self.event_log.add('login_failed', self.login_count)
            raise RuntimeError(f'Scripted login failure number {self.login_count}')
        self.current_token = f'token-{self.login_count}'
        self.event_log.add('login', self.current_token)
        return self.current_token

    def replace_elsewhere(self, token):
        """Replaces the token as another process logging in would.

        Args:
            token (str): The token the other process obtained.

        Returns:
            None: This method returns nothing.
        """
        self.current_token = token
        self.event_log.add('login_elsewhere', token)


class ScenarioContext:
    """Everything one scenario runs against.

    Attributes:
        event_log (EventLog): The scenario's ordered record.
        redis (RecordingRedis): The stand-in Redis client.
        plan (ConnectionPlan): The scripted connections.
        websocket_module (FakeWebsocketModule): The stand-in `websocket` package.
        logins (LoginLedger): The broker's login state.
        logger (logging.Logger): A logger whose lines go into the record.
    """

    def __init__(self, name, connections):
        """Builds fresh stand-ins for one scenario.

        Args:
            name (str): The scenario's name, used for the logger.
            connections (list): The scripted connections, as `ConnectionPlan` takes them.

        Returns:
            None: This method returns nothing.
        """
        self.event_log = EventLog()
        self.redis = RecordingRedis(self.event_log)
        self.plan = ConnectionPlan(connections)
        self.websocket_module = FakeWebsocketModule(self.event_log, self.plan)
        self.logins = LoginLedger(self.event_log)
        self.logger = logging.Logger(f'websocket_feeds.{name}', level=logging.DEBUG)
        self.logger.addHandler(CapturingHandler(self.event_log))

    def use_instant_waits(self, socket):
        """Replaces a socket's stop event so its backoff waits return at once and are recorded.

        The scenario ends by closing the socket when the scripted connections run out.

        Args:
            socket (object): The socket, which keeps its stop event in `_stop`.

        Returns:
            None: This method returns nothing.
        """
        socket._stop = InstantEvent(self.event_log)
        self.plan.on_exhausted = socket.close


class ScriptLoader:
    """Loads the extensionless scripts in `bin/` as modules without running them.

    Attributes:
        loaded (dict): Script paths to the modules already loaded.
    """

    def __init__(self):
        """Starts with nothing loaded.

        Returns:
            None: This method returns nothing.
        """
        self.loaded = {}

    def load(self, relative_path):
        """Loads a script once, under a module name that is not `__main__`, so its `main()` does not run.

        Args:
            relative_path (str): The script's path from the project root, such as `bin/zerodha/orders/websocket_order_details`.

        Returns:
            types.ModuleType: The loaded script.
        """
        if relative_path in self.loaded:
            return self.loaded[relative_path]
        module_name = 'websocket_feeds_script_' + relative_path.replace('/', '_')
        path = str(PROJECT_ROOT / relative_path)
        loader = importlib.machinery.SourceFileLoader(module_name, path)
        specification = importlib.util.spec_from_loader(module_name, loader)
        module = importlib.util.module_from_spec(specification)
        loader.exec_module(module)
        self.loaded[relative_path] = module
        return module


class PatchedWorld:
    """Replaces modules and clock functions for the length of one scenario, and puts them back afterwards.

    Attributes:
        context (ScenarioContext): The scenario being run.
        stub_modules (dict): Module names to the stand-ins placed in `sys.modules`.
        datetime_holders (list): Modules whose `datetime` name is replaced with `FrozenDatetime`.
        saved_modules (dict): Module names to what `sys.modules` held before, or None.
        saved_datetimes (list): Pairs of a module and the `datetime` it held before.
        saved_time (callable | None): The real `time.time`, while it is replaced.
    """

    def __init__(self, context, stub_modules, datetime_holders):
        """Keeps what to replace.

        Args:
            context (ScenarioContext): The scenario being run.
            stub_modules (dict): Module names to the stand-ins placed in `sys.modules`; `websocket` is always added.
            datetime_holders (list): Modules whose `datetime` name is replaced with `FrozenDatetime`.

        Returns:
            None: This method returns nothing.
        """
        self.context = context
        self.stub_modules = dict(stub_modules)
        self.stub_modules['websocket'] = context.websocket_module
        self.datetime_holders = list(datetime_holders)
        self.saved_modules = {}
        self.saved_datetimes = []
        self.saved_time = None

    def __enter__(self):
        """Installs the stand-ins.

        Returns:
            PatchedWorld: This object.
        """
        for name, stub in self.stub_modules.items():
            self.saved_modules[name] = sys.modules.get(name)
            sys.modules[name] = stub
        for holder in self.datetime_holders:
            self.saved_datetimes.append((holder, holder.datetime))
            holder.datetime = FrozenDatetime
        self.saved_time = time.time
        time.time = self.frozen_time
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Puts back everything that was replaced.

        Args:
            exception_type (type | None): The exception's class, if one is leaving the block.
            exception (BaseException | None): The exception, if one is leaving the block.
            traceback (types.TracebackType | None): Its traceback.

        Returns:
            bool: False, so an exception is never swallowed.
        """
        time.time = self.saved_time
        for holder, original in self.saved_datetimes:
            holder.datetime = original
        for name, original in self.saved_modules.items():
            if original is None:
                del sys.modules[name]
            else:
                sys.modules[name] = original
        return False

    def frozen_time(self):
        """Answers the frozen moment as an epoch.

        Returns:
            float: The epoch of `FROZEN_MOMENT`.
        """
        return FROZEN_MOMENT.timestamp()
