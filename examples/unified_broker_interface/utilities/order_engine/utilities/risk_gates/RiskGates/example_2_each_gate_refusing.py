"""Shows each risk gate refusing an order, with the HTTP status the engine answers with, and the gates built without the optional ones.

A refusal from a gate is a `RefusedRequestError`, whose `status` and `body` become the answer to the caller. The loss lockout answers 403, because the order is understood and deliberately refused. The rate budget answers 503 when it is full or when Redis cannot be read, because the order could be sent a moment later. The daily order count answers 429. When the daily count reserved a place and a later gate then stops the order, `release_reservation` gives the place back. Dhan is capped at two messages with half kept for exits, so one entry is sent (its `count_sent` is called by hand, standing in for `BrokerOrders.send`), the second entry is refused, and an exit still gets a place.

The gates here are the real classes over one small stand-in Redis client. The stand-in holds a funds document showing the day down 7,000 against a 5,000 limit, keeps the daily counts, and runs simplified versions of the two Lua scripts; its rate window never empties, and it can be told to fail the next script call with `redis.RedisError`. The rate budget waits zero seconds for room, so a full window refuses at once. The real loggers are used, so the rate budget's warning goes to standard error and does not appear in the recorded output.

The last part builds `RiskGates` with no throttle and no daily count. The throttle then allows every move, `refuse_if_capped` and `release_reservation` do nothing, and `counts` has no `daily_count` entry.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/risk_gates/RiskGates/example_2_each_gate_refusing.py
"""

import json
import logging

import redis

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.daily_order_count import (
    DailyOrderCount,
)
from unified_broker_interface.utilities.order_engine.utilities.loss_lockout import (
    LossLockout,
)
from unified_broker_interface.utilities.order_engine.utilities.order_to_trade_ratio import (
    OrderToTradeRatio,
)
from unified_broker_interface.utilities.order_engine.utilities.rate_budget import (
    RateBudget,
)
from unified_broker_interface.utilities.order_engine.utilities.risk_gates import (
    RiskGates,
)


class GateRedis:
    """A stand-in for the Redis client the gates share.

    Attributes:
        strings (dict): Each string key's value.
        window_counts (dict): How many messages each rate window key has counted.
        fail_next_script (bool): Whether the next script call raises `redis.RedisError`.
    """

    def __init__(self):
        """Builds the stand-in with nothing stored.

        Returns:
            None: This method returns nothing.
        """
        self.strings = {}
        self.window_counts = {}
        self.fail_next_script = False

    def register_script(self, script_text):
        """Returns a callable that does what the named script does.

        Args:
            script_text (str): The script's Lua source, used only to tell the two scripts apart.

        Returns:
            object: The method standing in for that script.
        """
        if 'ZREMRANGEBYSCORE' in script_text:
            return self.run_window_script
        return self.run_reserve_script

    def run_window_script(self, keys, args):
        """Counts one message in every window if all have room, in windows that never empty.

        Args:
            keys (list): The window keys.
            args (list): A member name, then a window length in microseconds and a limit for each key.

        Returns:
            int: 0 when counted, otherwise a wait of one second in microseconds.

        Raises:
            redis.RedisError: When the stand-in was told to fail this call.
        """
        if self.fail_next_script:
            self.fail_next_script = False
            raise redis.RedisError('Connection reset by peer')
        for position, key in enumerate(keys):
            limit = float(args[position * 2 + 2])
            if self.window_counts.get(key, 0) >= limit:
                return 1000000
        for key in keys:
            self.window_counts[key] = self.window_counts.get(key, 0) + 1
        return 0

    def run_reserve_script(self, keys, args):
        """Adds one to a daily count when it is below the limit.

        Args:
            keys (list): The count's key.
            args (list): The limit and the expiry epoch.

        Returns:
            int: The count after adding one, or minus one less the count when it was already at the limit.
        """
        sent = int(self.strings.get(keys[0], '0'))
        if sent >= int(args[0]):
            return -1 - sent
        self.strings[keys[0]] = str(sent + 1)
        return sent + 1

    def get(self, key):
        """Reads a string key.

        Args:
            key (str): The key.

        Returns:
            str | None: The value, or None when missing.
        """
        return self.strings.get(key)

    def decr(self, key):
        """Takes one from a count.

        Args:
            key (str): The key.

        Returns:
            int: The value afterwards.
        """
        value = int(self.strings.get(key, '0')) - 1
        self.strings[key] = str(value)
        return value


class EachGateRefusingExample:
    """Makes each gate refuse in turn, then shows the gates without the optional ones.

    Attributes:
        cache (GateRedis): The stand-in Redis client.
        logger (logging.Logger): The logger.
        gates (RiskGates): The gates being shown.
    """

    def __init__(self):
        """Builds the gates with a losing day, one message per window and a Dhan cap of two.

        Returns:
            None: This method returns nothing.
        """
        self.logger = logging.getLogger('example')
        self.cache = GateRedis()
        funds = {
            'pnl': {
                'realized': -6500.0,
                'unrealized': -500.0,
            },
        }
        self.cache.strings['unified:portfolio:funds'] = json.dumps(funds)
        caps = {
            'dhan': 2,
        }
        self.gates = RiskGates(
            RateBudget(self.cache, 0, 1, 0, self.logger),
            LossLockout(self.cache, 5000.0, self.logger),
            OrderToTradeRatio(),
            daily_count=DailyOrderCount(self.cache, caps, 0.5, self.logger),
        )

    def show_refusal(self, label, refusal):
        """Prints one refusal's status and body.

        Args:
            label (str): What was refused.
            refusal (RefusedRequestError): The refusal.

        Returns:
            None: This method returns nothing.
        """
        print(f'{label}: {refusal.status} {refusal.body}')

    def run(self):
        """Prints each refusal, the reservation being given back, and the gates without optional parts.

        Returns:
            None: This method returns nothing.
        """
        intent = {
            'intent_id': 'b9f0c1d2-0000-4000-8000-000000000002',
        }
        try:
            self.gates.check_before_accepting(intent)
        except RefusedRequestError as refusal:
            self.show_refusal('Loss lockout', refusal)
        self.gates.take_rate_token('zerodha')
        try:
            self.gates.take_rate_token('zerodha')
        except RefusedRequestError as refusal:
            self.show_refusal('Rate budget full', refusal)
        self.cache.fail_next_script = True
        try:
            self.gates.take_rate_token('fyers')
        except RefusedRequestError as refusal:
            self.show_refusal('Rate budget unreadable', refusal)
        self.gates.refuse_if_capped('dhan', False)
        self.gates.daily_count.count_sent('dhan')
        try:
            self.gates.refuse_if_capped('dhan', False)
        except RefusedRequestError as refusal:
            self.show_refusal('Daily cap', refusal)
        self.gates.refuse_if_capped('dhan', True)
        print(f'Dhan count with an exit reserved: {self.cache.get("unified:orders:daily_count:dhan")}')
        self.gates.release_reservation()
        print(f'Dhan count after the exit was not sent: {self.cache.get("unified:orders:daily_count:dhan")}')
        print(f'Counts: {self.gates.counts()}')
        plain_gates = RiskGates(
            RateBudget(GateRedis(), 0, 0, 0, self.logger),
            LossLockout(GateRedis(), 0, self.logger),
            OrderToTradeRatio(),
        )
        plain_gates.refuse_if_capped('dhan', False)
        plain_gates.release_reservation()
        plain_gates.record_reprice('P2-L1')
        print(f'Without a throttle, reprice P2-L1 at once: {plain_gates.allow_reprice("P2-L1")}')
        print(f'Counts without the optional gates: {plain_gates.counts()}')


if __name__ == '__main__':
    EachGateRefusingExample().run()
