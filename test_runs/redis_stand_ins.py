"""In-memory stand-ins for the parts of a Redis client the order suites use, shared by every suite that needs them.

Every direct command and every pipeline execution counts as one round trip, and a round trip can be made to fail with `redis.RedisError`. The engine stand-ins add the stream, list, set and key commands the order engine uses, so a suite can run the engine itself against the same memory the REST API routes read.
"""

import threading
import time

import redis


class FakeRateWindowScript:
    """What the rate budget's Lua script does, run against the stand-in's memory.

    Redis runs a script as one step with nothing interleaved, so the stand-in holds a lock for the whole call, or two threads could both find room for one last message.

    Attributes:
        fake_redis (FakeRedis): The stand-in whose windows are counted.
        lock (threading.Lock): Makes each call one uninterrupted step.
    """

    def __init__(self, fake_redis):
        """Builds the script.

        Args:
            fake_redis (FakeRedis): The stand-in whose windows are counted.

        Returns:
            None: This method returns nothing.
        """
        self.fake_redis = fake_redis
        self.lock = threading.Lock()

    def __call__(self, keys, args):
        """Counts one message in every named window if all have room, or says how long until they do.

        Args:
            keys (list): The window keys.
            args (list): The window length in microseconds, a member name, and one limit per key.

        Returns:
            int: 0 when counted, otherwise the microseconds until there is room.

        Raises:
            redis.RedisError: When this round trip is set to fail.
        """
        self.fake_redis.start_round_trip()
        with self.lock:
            return self.count_one(keys, args)

    def count_one(self, keys, args):
        """Counts one message in every named window if all have room, holding the call's lock.

        Args:
            keys (list): The window keys.
            args (list): The window length in microseconds, a member name, and one limit per key.

        Returns:
            int: 0 when counted, otherwise the microseconds until there is room.
        """
        now = int(time.monotonic() * 1000000)
        window = int(args[0])
        longest_wait = 0
        for position, key in enumerate(keys):
            limit = float(args[position + 2])
            kept = []
            for moment in self.fake_redis.rate_windows.get(key, []):
                if moment > now - window:
                    kept.append(moment)
            self.fake_redis.rate_windows[key] = kept
            if len(kept) >= limit:
                wait = kept[0] + window - now
                if wait > longest_wait:
                    longest_wait = wait
        if longest_wait > 0:
            return longest_wait
        for key in keys:
            self.fake_redis.rate_windows[key].append(now)
            self.fake_redis.rate_log.append((key, now))
        return 0


class FakeRedis:
    """An in-memory stand-in for the parts of a Redis client the order routes use.

    Every direct command and every pipeline execution counts as one round trip, and a round trip can be made to fail with `redis.RedisError`.

    Attributes:
        strings (dict): String keys to their values.
        hashes (dict): Hash keys to dictionaries of fields and values.
        sorted_sets (dict): Sorted set keys to lists of members, all scored 0.
        rate_windows (dict): Each rate budget key to the monotonic times, in microseconds, of the messages counted in it.
        rate_log (list): Every message the rate window script counted, as `(key, microseconds)`, never pruned.
        round_trips (int): How many round trips have been made.
        failing_round_trip (int | None): The 1-based round trip that raises `redis.RedisError`, or None when none fails.
    """

    def __init__(self):
        """Builds an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.strings = {}
        self.hashes = {}
        self.sorted_sets = {}
        self.rate_windows = {}
        self.rate_log = []
        self.round_trips = 0
        self.failing_round_trip = None

    def register_script(self, script_text):
        """Registers a Lua script, which here can only be the rate budget's sliding window.

        Args:
            script_text (str): The script's source.

        Returns:
            FakeRateWindowScript: A callable that does what the script does, in one round trip.

        Raises:
            NotImplementedError: When the script is not the rate window, which this stand-in cannot run.
        """
        if 'ZREMRANGEBYSCORE' not in script_text:
            raise NotImplementedError('the stand-in runs only the rate window script')
        return FakeRateWindowScript(self)

    def start_round_trip(self):
        """Counts one round trip and raises when it is the one set to fail.

        Returns:
            None: This method returns nothing.

        Raises:
            redis.RedisError: When this round trip is the failing one.
        """
        self.round_trips = self.round_trips + 1
        if self.round_trips == self.failing_round_trip:
            raise redis.RedisError('stand-in failure')

    def pipeline(self, transaction=True):
        """Starts a pipeline over this stand-in.

        Args:
            transaction (bool): Accepted for compatibility with redis-py and ignored.

        Returns:
            FakePipeline: The pipeline.
        """
        del transaction
        return FakePipeline(self)

    def get(self, key):
        """Reads a string key in its own round trip.

        Args:
            key (str): The key.

        Returns:
            str | None: The value, or None when the key is absent.

        Raises:
            redis.RedisError: When this round trip is set to fail.
        """
        self.start_round_trip()
        return self.run_get(key)

    def exists(self, key):
        """Counts whether a key is held, in its own round trip.

        Args:
            key (str): The key.

        Returns:
            int: 1 when the key is held as a string, hash or sorted set, and 0 when it is not.

        Raises:
            redis.RedisError: When this round trip is set to fail.
        """
        self.start_round_trip()
        if key in self.strings:
            return 1
        if self.hashes.get(key):
            return 1
        if self.sorted_sets.get(key):
            return 1
        return 0

    def hget(self, key, field):
        """Reads one hash field in its own round trip.

        Args:
            key (str): The hash key.
            field (str): The field.

        Returns:
            str | None: The value, or None when absent.

        Raises:
            redis.RedisError: When this round trip is set to fail.
        """
        self.start_round_trip()
        return self.run_hget(key, field)

    def hmget(self, key, fields):
        """Reads several hash fields in its own round trip.

        Args:
            key (str): The hash key.
            fields (list): The field names, as strings.

        Returns:
            list: One value or None per field, in the order asked.

        Raises:
            redis.RedisError: When this round trip is set to fail.
        """
        self.start_round_trip()
        return self.run_hmget(key, fields)

    def hgetall(self, key):
        """Reads every field of a hash in its own round trip.

        Args:
            key (str): The hash key.

        Returns:
            dict: The hash's fields to their values, empty when there is no such hash.

        Raises:
            redis.RedisError: When this round trip is set to fail.
        """
        self.start_round_trip()
        return dict(self.hashes.get(key, {}))

    def incr(self, key):
        """Adds one to a string key in its own round trip.

        Args:
            key (str): The key.

        Returns:
            int: The value after the increment.

        Raises:
            redis.RedisError: When this round trip is set to fail.
        """
        self.start_round_trip()
        return self.run_incr(key)

    def zrangebylex(self, key, minimum, maximum, start=None, num=None):
        """Reads a lexical range of a sorted set in its own round trip.

        Args:
            key (str): The sorted set key.
            minimum (bytes | str): The lower bound, starting with `[` for inclusive or `(` for exclusive.
            maximum (bytes | str): The upper bound, in the same form.
            start (int | None): How many matching members to skip.
            num (int | None): The most members to return.

        Returns:
            list: The matching members, as strings.

        Raises:
            redis.RedisError: When this round trip is set to fail.
        """
        self.start_round_trip()
        return self.run_zrangebylex(key, minimum, maximum, start, num)

    def run_get(self, key):
        """Reads a string key without counting a round trip.

        Args:
            key (str): The key.

        Returns:
            str | None: The value, or None when absent.
        """
        return self.strings.get(key)

    def run_hget(self, key, field):
        """Reads one hash field without counting a round trip.

        Args:
            key (str): The hash key.
            field (str): The field.

        Returns:
            str | None: The value, or None when absent.
        """
        return self.hashes.get(key, {}).get(field)

    def run_hmget(self, key, fields):
        """Reads several hash fields without counting a round trip.

        Args:
            key (str): The hash key.
            fields (list): The field names, as strings.

        Returns:
            list: One value or None per field.
        """
        values = []
        stored_fields = self.hashes.get(key, {})
        for field in fields:
            values.append(stored_fields.get(field))
        return values

    def run_incr(self, key):
        """Adds one to a string key without counting a round trip.

        Args:
            key (str): The key.

        Returns:
            int: The value after the increment.
        """
        value = int(self.strings.get(key) or 0) + 1
        self.strings[key] = str(value)
        return value

    def run_zrangebylex(self, key, minimum, maximum, start, num):
        """Reads a lexical range of a sorted set without counting a round trip.

        Args:
            key (str): The sorted set key.
            minimum (bytes | str): The lower bound, starting with `[` or `(`.
            maximum (bytes | str): The upper bound, starting with `[` or `(`.
            start (int | None): How many matching members to skip.
            num (int | None): The most members to return.

        Returns:
            list: The matching members, as strings.
        """
        minimum_bytes = self.as_bytes(minimum)
        maximum_bytes = self.as_bytes(maximum)
        members = sorted(self.sorted_sets.get(key, []), key=self.as_bytes)
        matching = []
        for member in members:
            member_bytes = self.as_bytes(member)
            if not self.above_lower_bound(member_bytes, minimum_bytes):
                continue
            if not self.below_upper_bound(member_bytes, maximum_bytes):
                continue
            matching.append(member)
        if start is not None:
            matching = matching[start:]
        if num is not None:
            matching = matching[:num]
        return matching

    def as_bytes(self, value):
        """Turns a member or bound into bytes for comparison.

        Args:
            value (bytes | str): The value.

        Returns:
            bytes: The value as UTF-8 bytes.
        """
        if isinstance(value, bytes):
            return value
        return value.encode('utf-8')

    def above_lower_bound(self, member_bytes, bound_bytes):
        """Whether a member lies at or above a lexical lower bound.

        Args:
            member_bytes (bytes): The member.
            bound_bytes (bytes): The bound, starting with `[` or `(`, or `-` for no bound.

        Returns:
            bool: True when the member is inside the bound.
        """
        if bound_bytes == b'-':
            return True
        if bound_bytes.startswith(b'['):
            return member_bytes >= bound_bytes[1:]
        return member_bytes > bound_bytes[1:]

    def below_upper_bound(self, member_bytes, bound_bytes):
        """Whether a member lies at or below a lexical upper bound.

        Args:
            member_bytes (bytes): The member.
            bound_bytes (bytes): The bound, starting with `[` or `(`, or `+` for no bound.

        Returns:
            bool: True when the member is inside the bound.
        """
        if bound_bytes == b'+':
            return True
        if bound_bytes.startswith(b'['):
            return member_bytes <= bound_bytes[1:]
        return member_bytes < bound_bytes[1:]


class FakePipeline:
    """A queue of commands sent to a `FakeRedis` in one round trip.

    Attributes:
        fake_redis (FakeRedis): The stand-in the commands run against.
        commands (list): Queued `(command name, arguments)` tuples.
    """

    def __init__(self, fake_redis):
        """Builds an empty pipeline.

        Args:
            fake_redis (FakeRedis): The stand-in the commands run against.

        Returns:
            None: This method returns nothing.
        """
        self.fake_redis = fake_redis
        self.commands = []

    def get(self, key):
        """Queues a string read.

        Args:
            key (str): The key.

        Returns:
            FakePipeline: This pipeline.
        """
        self.commands.append((
            'get',
            [
                key,
            ],
        ))
        return self

    def hget(self, key, field):
        """Queues a hash field read.

        Args:
            key (str): The hash key.
            field (str): The field.

        Returns:
            FakePipeline: This pipeline.
        """
        self.commands.append((
            'hget',
            [
                key,
                field,
            ],
        ))
        return self

    def hmget(self, key, fields):
        """Queues a read of several hash fields.

        Args:
            key (str): The hash key.
            fields (list): The field names, as strings.

        Returns:
            FakePipeline: This pipeline.
        """
        self.commands.append((
            'hmget',
            [
                key,
                list(fields),
            ],
        ))
        return self

    def incr(self, key):
        """Queues an increment.

        Args:
            key (str): The key.

        Returns:
            FakePipeline: This pipeline.
        """
        self.commands.append((
            'incr',
            [
                key,
            ],
        ))
        return self

    def execute(self):
        """Runs every queued command in one round trip.

        Returns:
            list: One reply per queued command, in order.

        Raises:
            redis.RedisError: When this round trip is set to fail.
            ValueError: When a queued command is not one the stand-in knows.
        """
        self.fake_redis.start_round_trip()
        replies = []
        for command_name, arguments in self.commands:
            if command_name == 'get':
                replies.append(self.fake_redis.run_get(*arguments))
            elif command_name == 'hget':
                replies.append(self.fake_redis.run_hget(*arguments))
            elif command_name == 'hmget':
                replies.append(self.fake_redis.run_hmget(*arguments))
            elif command_name == 'incr':
                replies.append(self.fake_redis.run_incr(*arguments))
            else:
                raise ValueError(f'unsupported stand-in command: {command_name!r}')
        self.commands = []
        return replies


class FakeEngineRedis(FakeRedis):
    """The order routes' stand-in, widened with the stream and list commands the handoff uses.

    `blpop` never blocks: it answers with whatever was seeded onto the reply list, or with None, which is what a real wait that ran out of time returns. A scenario therefore exercises the timeout path without waiting for it.

    Attributes:
        streams (dict): Stream keys to lists of `(entry_id, fields)`.
        lists (dict): List keys to their entries.
    """

    def __init__(self):
        """Builds an empty stand-in with no streams and no lists.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.streams = {}
        self.lists = {}

    def xadd(self, key, fields, maxlen=None, approximate=False):
        """Appends one entry to a stream in its own round trip.

        Args:
            key (str): The stream key.
            fields (dict): The entry's fields.
            maxlen (int | None): Accepted for compatibility with redis-py and ignored, since nothing here writes enough entries to trim.
            approximate (bool): Accepted for compatibility with redis-py and ignored.

        Returns:
            str: The entry's id.

        Raises:
            redis.RedisError: When this round trip is the failing one.
        """
        del maxlen, approximate
        self.start_round_trip()
        return self.run_xadd(key, fields)

    def run_xadd(self, key, fields):
        """Appends one entry to a stream, as part of a round trip already counted.

        Args:
            key (str): The stream key.
            fields (dict): The entry's fields.

        Returns:
            str: The entry's id.
        """
        entries = self.streams.setdefault(key, [])
        entry_id = f'{len(entries) + 1}-0'
        entries.append((entry_id, dict(fields)))
        return entry_id

    def blpop(self, key, timeout=None):
        """Takes the first entry off a list, answering None when there is none.

        Args:
            key (str): The list key.
            timeout (float | None): Accepted for compatibility with redis-py and ignored, since the stand-in never waits.

        Returns:
            tuple | None: `(key, value)` when the list held something, and None when it did not.

        Raises:
            redis.RedisError: When this round trip is the failing one.
        """
        del timeout
        self.start_round_trip()
        entries = self.lists.get(key)
        if not entries:
            return None
        value = entries.pop(0)
        if not entries:
            self.lists.pop(key, None)
        return key, value


class FakeEngineStoreRedis(FakeEngineRedis):
    """The handoff's stand-in, widened with the consumer group, list and lock commands the engine uses.

    Attributes:
        groups (dict): Stream keys to the set of group names created on them.
        delivered (dict): Stream keys to every entry id ever handed out, which is what `>` reads past.
        pending (dict): Stream keys to the entry ids handed out but not yet acknowledged.
        expiries (dict): Keys to the expiry in seconds last set on them.
    """

    def __init__(self):
        """Builds an empty stand-in.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.groups = {}
        self.delivered = {}
        self.pending = {}
        self.expiries = {}
        self.sets = {}

    def xgroup_create(self, key, group, id=None, mkstream=False):
        """Creates a consumer group, raising when it is already there, as Redis does.

        Args:
            key (str): The stream key.
            group (str): The group name.
            id (str | None): Accepted for compatibility with redis-py and ignored.
            mkstream (bool): Creates the stream when it does not exist.

        Returns:
            bool: True.

        Raises:
            Exception: With BUSYGROUP in its message when the group already exists.
        """
        if not mkstream and key not in self.streams:
            raise Exception(
                'ERR The XGROUP subcommand requires the key to exist',
            )
        del id
        self.streams.setdefault(key, [])
        created = self.groups.setdefault(key, set())
        if group in created:
            raise Exception('BUSYGROUP Consumer Group name already exists')
        created.add(group)
        return True

    def xreadgroup(self, group, consumer, streams, count=None, block=None):
        """Reads new or pending entries for one consumer group, never blocking.

        Args:
            group (str): The group name.
            consumer (str): The consumer name.
            streams (dict): Stream keys to `0` for pending entries or `>` for new ones.
            count (int | None): The most entries to read.
            block (int | None): Accepted for compatibility with redis-py and ignored, since the stand-in never waits.

        Returns:
            list: `(stream_key, entries)` pairs, with entries as `(entry_id, fields)`.

        Raises:
            redis.RedisError: When this round trip is the failing one.
        """
        del group, consumer, block
        self.start_round_trip()
        response = []
        for key, position in streams.items():
            delivered = self.delivered.setdefault(key, [])
            pending = self.pending.setdefault(key, [])
            entries = []
            for entry_id, fields in self.streams.get(key, []):
                if count is not None and len(entries) >= count:
                    break
                if position == '0':
                    if entry_id in pending:
                        entries.append((entry_id, fields))
                elif entry_id not in delivered:
                    delivered.append(entry_id)
                    pending.append(entry_id)
                    entries.append((entry_id, fields))
            if entries:
                response.append((key, entries))
        return response

    def xack(self, key, group, entry_id):
        """Acknowledges one delivered entry.

        Args:
            key (str): The stream key.
            group (str): The group name.
            entry_id (str): The entry's id.

        Returns:
            int: 1 when the entry was delivered and is now acknowledged, and 0 otherwise.
        """
        del group
        self.start_round_trip()
        pending = self.pending.setdefault(key, [])
        if entry_id in pending:
            pending.remove(entry_id)
            return 1
        return 0

    def set(self, key, value, nx=False, ex=None):
        """Sets a string key, optionally only when it does not exist.

        Args:
            key (str): The key.
            value (str): The value.
            nx (bool): Only set the key when it does not already exist.
            ex (int | None): The expiry in seconds.

        Returns:
            bool | None: True when the key was set, and None when `nx` was given and it already existed.
        """
        self.start_round_trip()
        return self.run_set(key, value, nx, ex)

    def run_set(self, key, value, nx=False, ex=None):
        """Sets a string key, as part of a round trip already counted.

        Args:
            key (str): The key.
            value (str): The value.
            nx (bool): Only set the key when it does not already exist.
            ex (int | None): The expiry in seconds.

        Returns:
            bool | None: True when the key was set, and None when `nx` was given and it already existed.
        """
        if nx and key in self.strings:
            return None
        self.strings[key] = value
        if ex is not None:
            self.expiries[key] = ex
        return True

    def expire(self, key, seconds):
        """Records an expiry on a key.

        Args:
            key (str): The key.
            seconds (int): The expiry in seconds.

        Returns:
            bool: True when the key exists.
        """
        self.start_round_trip()
        self.expiries[key] = seconds
        return key in self.strings or key in self.lists

    def delete(self, key):
        """Removes a key.

        Args:
            key (str): The key.

        Returns:
            int: 1 when the key existed, and 0 otherwise.
        """
        self.start_round_trip()
        self.expiries.pop(key, None)
        if self.strings.pop(key, None) is not None:
            return 1
        return 0

    def smembers(self, key):
        """Every member of a set.

        Args:
            key (str): The set key.

        Returns:
            set: The members.
        """
        self.start_round_trip()
        return set(self.sets.get(key, set()))

    def run_hgetall(self, key):
        """Every field in a hash, without counting a round trip of its own.

        Args:
            key (str): The hash key.

        Returns:
            dict: The fields and values, or an empty dictionary.
        """
        return dict(self.hashes.get(key, {}))

    def run_hset(self, key, field, value):
        """Sets a hash field, without counting a round trip of its own.

        Args:
            key (str): The hash key.
            field (str): The field.
            value (str): The value.

        Returns:
            int: 1 when the field is new, and 0 when it was replaced.
        """
        fields = self.hashes.setdefault(key, {})
        new_field = field not in fields
        fields[field] = value
        return 1 if new_field else 0

    def run_sadd(self, key, member):
        """Adds a set member, without counting a round trip of its own.

        Args:
            key (str): The set key.
            member (str): The member.

        Returns:
            int: 1 when the member is new, and 0 when it was already there.
        """
        members = self.sets.setdefault(key, set())
        new_member = member not in members
        members.add(member)
        return 1 if new_member else 0

    def run_srem(self, key, member):
        """Removes a set member, without counting a round trip of its own.

        Args:
            key (str): The set key.
            member (str): The member.

        Returns:
            int: 1 when the member was there, and 0 otherwise.
        """
        members = self.sets.setdefault(key, set())
        if member in members:
            members.discard(member)
            return 1
        return 0

    def run_expireat(self, key, moment):
        """Records an absolute expiry on a key, without counting a round trip of its own.

        Args:
            key (str): The key.
            moment (int): The epoch the key expires at.

        Returns:
            bool: True.
        """
        self.expiries[key] = moment
        return True

    def run_delete(self, key):
        """Removes a key of any type, without counting a round trip of its own.

        Args:
            key (str): The key.

        Returns:
            int: 1 when the key existed, and 0 otherwise.
        """
        self.expiries.pop(key, None)
        existed = (
            self.strings.pop(key, None) is not None
            or self.hashes.pop(key, None) is not None
            or self.sets.pop(key, None) is not None
            or self.lists.pop(key, None) is not None
        )
        return 1 if existed else 0

    def run_rpush(self, key, value):
        """Appends to a list, without counting a round trip of its own.

        Args:
            key (str): The list key.
            value (str): The value.

        Returns:
            int: The list's new length.
        """
        entries = self.lists.setdefault(key, [])
        entries.append(value)
        return len(entries)

    def run_expire(self, key, seconds):
        """Records an expiry on a key, without counting a round trip of its own.

        Args:
            key (str): The key.
            seconds (int): The expiry in seconds.

        Returns:
            bool: True.
        """
        self.expiries[key] = seconds
        return True

    def pipeline(self, transaction=True):
        """Starts a pipeline that also understands the list commands the engine queues.

        Args:
            transaction (bool): Accepted for compatibility with redis-py and ignored.

        Returns:
            FakeEnginePipeline: The pipeline.
        """
        del transaction
        return FakeEnginePipeline(self)


class FakeEnginePipeline(FakePipeline):
    """The order routes' pipeline, widened with the list, string and stream commands the engine and the list handoff queue."""

    def set(self, key, value, nx=False, ex=None):
        """Queues a string write.

        Args:
            key (str): The key.
            value (str): The value.
            nx (bool): Only set the key when it does not already exist.
            ex (int | None): The expiry in seconds.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('set', (key, value, nx, ex)))
        return self

    def xadd(self, key, fields, maxlen=None, approximate=False):
        """Queues an append to a stream.

        Args:
            key (str): The stream key.
            fields (dict): The entry's fields.
            maxlen (int | None): Accepted for compatibility with redis-py and ignored.
            approximate (bool): Accepted for compatibility with redis-py and ignored.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        del maxlen, approximate
        self.commands.append(('xadd', (key, fields)))
        return self

    def rpush(self, key, value):
        """Queues an append to a list.

        Args:
            key (str): The list key.
            value (str): The value.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('rpush', (key, value)))
        return self

    def expire(self, key, seconds):
        """Queues an expiry on a key.

        Args:
            key (str): The key.
            seconds (int): The expiry in seconds.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('expire', (key, seconds)))
        return self

    def hset(self, key, field, value):
        """Queues a hash write.

        Args:
            key (str): The hash key.
            field (str): The field.
            value (str): The value.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('hset', (key, field, value)))
        return self

    def sadd(self, key, member):
        """Queues a set addition.

        Args:
            key (str): The set key.
            member (str): The member.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('sadd', (key, member)))
        return self

    def srem(self, key, member):
        """Queues a set removal.

        Args:
            key (str): The set key.
            member (str): The member.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('srem', (key, member)))
        return self

    def expireat(self, key, moment):
        """Queues an absolute expiry.

        Args:
            key (str): The key.
            moment (int): The epoch the key expires at.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('expireat', (key, moment)))
        return self

    def delete(self, key):
        """Queues a key removal.

        Args:
            key (str): The key.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('delete', (key,)))
        return self

    def hgetall(self, key):
        """Queues a read of every field in a hash.

        Args:
            key (str): The hash key.

        Returns:
            FakeEnginePipeline: This pipeline.
        """
        self.commands.append(('hgetall', (key,)))
        return self

    def execute(self):
        """Runs every queued command in one round trip.

        Returns:
            list: One reply per queued command, in order.

        Raises:
            redis.RedisError: When this round trip is set to fail.
            ValueError: When a queued command is not one the stand-in knows.
        """
        self.fake_redis.start_round_trip()
        replies = []
        for command_name, arguments in self.commands:
            if command_name == 'get':
                replies.append(self.fake_redis.run_get(*arguments))
            elif command_name == 'hget':
                replies.append(self.fake_redis.run_hget(*arguments))
            elif command_name == 'hmget':
                replies.append(self.fake_redis.run_hmget(*arguments))
            elif command_name == 'incr':
                replies.append(self.fake_redis.run_incr(*arguments))
            elif command_name == 'rpush':
                replies.append(self.fake_redis.run_rpush(*arguments))
            elif command_name == 'expire':
                replies.append(self.fake_redis.run_expire(*arguments))
            elif command_name == 'hset':
                replies.append(self.fake_redis.run_hset(*arguments))
            elif command_name == 'sadd':
                replies.append(self.fake_redis.run_sadd(*arguments))
            elif command_name == 'srem':
                replies.append(self.fake_redis.run_srem(*arguments))
            elif command_name == 'expireat':
                replies.append(self.fake_redis.run_expireat(*arguments))
            elif command_name == 'delete':
                replies.append(self.fake_redis.run_delete(*arguments))
            elif command_name == 'hgetall':
                replies.append(self.fake_redis.run_hgetall(*arguments))
            elif command_name == 'set':
                replies.append(self.fake_redis.run_set(*arguments))
            elif command_name == 'xadd':
                replies.append(self.fake_redis.run_xadd(*arguments))
            else:
                raise ValueError(
                    f'unsupported stand-in command: {command_name!r}'
                )
        self.commands = []
        return replies


class InlineEngineRedis(FakeEngineStoreRedis):
    """The engine stand-in, which runs an engine over the waiting intents when a reply list is waited on and is empty.

    Attributes:
        inline_engine (engine_stand_ins.InlineEngine | None): The engine to run, or None to answer a wait with nothing, as `FakeEngineRedis` does.
    """

    def __init__(self):
        """Builds an empty stand-in with no engine yet.

        Returns:
            None: This method returns nothing.
        """
        super().__init__()
        self.inline_engine = None

    def blpop(self, key, timeout=None):
        """Takes the first entry off a list, running the engine first when the list is empty.

        Args:
            key (str): The list key.
            timeout (float | None): Accepted for compatibility with redis-py and ignored.

        Returns:
            tuple | None: `(key, value)` when the list held something, and None when it did not.

        Raises:
            redis.RedisError: When this round trip is the failing one.
        """
        if not self.lists.get(key) and self.inline_engine is not None:
            self.inline_engine.place_waiting_intents()
        return super().blpop(key, timeout)
