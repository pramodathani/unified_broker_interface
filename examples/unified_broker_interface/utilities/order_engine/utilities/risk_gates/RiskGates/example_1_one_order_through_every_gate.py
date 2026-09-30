"""Takes one order through every risk gate the order engine applies, in the order the engine applies them, and prints the gates' counts.

`RiskGates` holds the engine's five limits together: the rate budget, the daily loss lockout, the order-to-trade ratio, the re-pricing throttle and the daily order count. The engine calls `check_before_accepting` before it creates a parent, `take_rate_token` and `refuse_if_capped` once it knows the broker, `count_sent` and `count_traded` as the order is sent and fills, and `allow_reprice` and `record_reprice` whenever a resting order wants to move. `counts` gathers what every gate has done for the engine's shutdown line.

The gates here are the real classes. They share one small stand-in Redis client, which holds the funds document the loss lockout reads, keeps the daily counts, and runs simplified versions of the two Lua scripts: its rate window never empties, which is harmless in a program that finishes in well under a second. The daily count's own `count_sent` is called by hand, standing in for `BrokerOrders.send`, which calls it in the real system once the message has gone out.

Notice that the second `allow_reprice` for the same leg is refused, because the throttle's minimum gap is thirty seconds.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/risk_gates/RiskGates/example_1_one_order_through_every_gate.py
"""

import json
import logging

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
from unified_broker_interface.utilities.order_engine.utilities.repricing_throttle import (
    RepricingThrottle,
)
from unified_broker_interface.utilities.order_engine.utilities.risk_gates import (
    RiskGates,
)


class GateRedis:
    """A stand-in for the Redis client the gates share.

    Attributes:
        strings (dict): Each string key's value.
        window_counts (dict): How many messages each rate window key has counted.
    """

    def __init__(self):
        """Builds the stand-in with nothing stored.

        Returns:
            None: This method returns nothing.
        """
        self.strings = {}
        self.window_counts = {}

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
        """
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


class OneOrderThroughEveryGateExample:
    """Passes one Zerodha order through every gate.

    Attributes:
        cache (GateRedis): The stand-in Redis client.
        gates (RiskGates): The gates being shown.
    """

    def __init__(self):
        """Builds every gate over the stand-in, with the day down 1,200 against a 5,000 limit.

        Returns:
            None: This method returns nothing.
        """
        logger = logging.getLogger('example')
        self.cache = GateRedis()
        funds = {
            'pnl': {
                'realized': -800.0,
                'unrealized': -400.0,
            },
        }
        self.cache.strings['unified:portfolio:funds'] = json.dumps(funds)
        caps = {
            'zerodha': 3000,
        }
        self.gates = RiskGates(
            RateBudget(self.cache, 0, 5, 0, logger),
            LossLockout(self.cache, 5000.0, logger),
            OrderToTradeRatio(),
            RepricingThrottle(30.0),
            DailyOrderCount(self.cache, caps, 0.05, logger),
        )

    def run(self):
        """Prints what each gate says as the order goes through.

        Returns:
            None: This method returns nothing.
        """
        intent = {
            'intent_id': 'b9f0c1d2-0000-4000-8000-000000000001',
        }
        self.gates.check_before_accepting(intent)
        print('Loss lockout: accepted')
        self.gates.take_rate_token('zerodha')
        print('Rate budget: token taken')
        self.gates.refuse_if_capped('zerodha', False)
        print(f'Daily count: place reserved, count {self.cache.get("unified:orders:daily_count:zerodha")}')
        self.gates.daily_count.count_sent('zerodha')
        self.gates.count_sent('zerodha')
        self.gates.release_reservation()
        print(f'After sending, count stays {self.cache.get("unified:orders:daily_count:zerodha")}')
        self.gates.count_traded('zerodha')
        print(f'Reprice P1-L1 now: {self.gates.allow_reprice("P1-L1")}')
        self.gates.record_reprice('P1-L1')
        print(f'Reprice P1-L1 again at once: {self.gates.allow_reprice("P1-L1")}')
        print('Counts:')
        for name, value in self.gates.counts().items():
            print(f'  {name}: {value}')


if __name__ == '__main__':
    OneOrderThroughEveryGateExample().run()
