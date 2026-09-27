"""Offline checks that each order type carries on from a caller's change to one of its legs.

`PUT /api/orders/modify` hands a change to an order the engine placed to the parent's order type, which sends it and then calls `on_leg_modified`. These checks build a parent of each type that keeps its own copy of a price or quantity, apply a change through `apply_outside_modification` with a stubbed broker, and check what the type made of it: a trailing stop's watermark, a peg's offset, a chaser's step time, a linked pair's other exit, and a slicer's remaining quantity. They also check that the recorded events replay to the same parameters, which is what keeps the change after a restart.

Nothing leaves the machine, and no Redis, database or credentials are used.

Typical usage:

    python -m test_runs.leg_modifications
"""

import decimal
import logging
import sys
import time

from test_runs import engine_stand_ins
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.registry import (
    SYNTHETIC_ORDER_CLASSES,
)

INSTRUMENT = '11111111-1111-5111-8111-000000000001'
PARENT = '44444444-3333-4222-8111-000000000000'


class AcceptedAnswer:
    """What the stub broker answers every change with.

    Attributes:
        outcome (str): Always `accepted`.
        status_message (None): No message.
        response_body (dict): An empty body.
    """

    def __init__(self):
        """Builds the answer.

        Returns:
            None: This method returns nothing.
        """
        self.outcome = 'accepted'
        self.status_message = None
        self.response_body = {}


class StubPlacement:
    """Stands in for the engine's placement: accepts every change and cancel, and serves one quote.

    Attributes:
        quote (dict | None): The quote `market_context` answers with.
        changes (list): Every change sent, as `(order_id, quantity, price, trigger_price)`.
    """

    def __init__(self, quote=None):
        """Builds the stub.

        Args:
            quote (dict | None): The quote to serve.

        Returns:
            None: This method returns nothing.
        """
        self.quote = quote
        self.changes = []

    def modify_leg(self, broker_name, broker_order_id, quantity=None, price=None, trigger_price=None):
        """Accepts a change and remembers it.

        Args:
            broker_name (str): The broker.
            broker_order_id (str): The order.
            quantity (int | None): The new quantity.
            price (decimal.Decimal | None): The new price.
            trigger_price (decimal.Decimal | None): The new trigger.

        Returns:
            AcceptedAnswer: The answer.
        """
        del broker_name
        self.changes.append((broker_order_id, quantity, price, trigger_price))
        return AcceptedAnswer()

    def market_context(self, instrument_id, needs_quote, needs_positions):
        """Serves the one quote.

        Args:
            instrument_id (str): The instrument, unused.
            needs_quote (bool): Unused.
            needs_positions (bool): Unused.

        Returns:
            tuple: None, the quote and None.
        """
        del instrument_id, needs_quote, needs_positions
        return None, self.quote, None


class StubParentStore:
    """Stands in for the Redis copy of the parents, keeping nothing."""

    def save(self, parent):
        """Accepts a parent without keeping it.

        Args:
            parent (ParentOrder): The parent.

        Returns:
            None: This method returns nothing.
        """
        del parent


class LegModificationChecks:
    """Runs every check and prints its result.

    Attributes:
        logger (logging.Logger): The logger handed to the order types, kept quiet.
        passed (int): How many checks passed.
        failed (list): The names of the checks that failed.
    """

    def __init__(self):
        """Builds the checks.

        Returns:
            None: This method returns nothing.
        """
        self.logger = logging.getLogger('test_runs.leg_modifications')
        self.logger.setLevel(logging.CRITICAL)
        self.passed = 0
        self.failed = []

    def check(self, name, condition, detail):
        """Records and prints one check.

        Args:
            name (str): The check's name.
            condition (bool): Whether it passed.
            detail (str): What was observed.

        Returns:
            None: This method returns nothing.
        """
        if condition:
            self.passed = self.passed + 1
            print(f'ok      {name}: {detail}')
        else:
            self.failed.append(name)
            print(f'FAILED  {name}: {detail}')

    def leg_event(self, number, role, side, quantity, price=None, trigger_price=None):
        """A `leg_answered` event for one acknowledged leg.

        Args:
            number (int): The leg's number within the parent.
            role (str): The leg's role.
            side (str): BUY or SELL.
            quantity (int): The quantity.
            price (float | None): The limit price.
            trigger_price (float | None): The trigger price.

        Returns:
            dict: The event.
        """
        return {
            'time': '2026-09-27T10:00:01+00:00',
            'parent_order_id': PARENT,
            'sequence': number + 1,
            'event': 'leg_answered',
            'leg_id': f'{PARENT}:{number}',
            'leg_role': role,
            'leg_state': 'acknowledged',
            'broker': 'flattrade',
            'broker_order_id': f'2609150000{number:04d}',
            'transaction_type': side,
            'quantity': quantity,
            'price': price,
            'trigger_price': trigger_price,
        }

    def runner(self, synthetic_type, parameters, legs, placement=None, body=None):
        """An order type holding a parent with the given parameters and legs.

        Args:
            synthetic_type (str): The type's name.
            parameters (dict): The type's parameters.
            legs (list): `leg_answered` events, one per leg.
            placement (StubPlacement | None): The placement, or a new one.
            body (dict | None): The caller's body, or a plain order.

        Returns:
            tuple: The runner (SyntheticOrder) and its event log (RecordingEventLog).
        """
        received = {
            'time': '2026-09-27T10:00:00+00:00',
            'parent_order_id': PARENT,
            'sequence': 1,
            'event': 'parent_received',
            'synthetic_type': synthetic_type,
            'parent_state': 'working',
            'instrument_id': INSTRUMENT,
            'detail': {
                'body': body or {
                    'instrument_id': INSTRUMENT,
                    'transaction_type': 'BUY',
                    'product': 'MIS',
                    'order_type': 'MARKET',
                    'quantity': 300,
                },
                'parameters': parameters,
            },
        }
        parent = ParentOrder.from_events([received] + legs)
        event_log = engine_stand_ins.RecordingEventLog()
        runner = SYNTHETIC_ORDER_CLASSES[synthetic_type](
            parent,
            placement or StubPlacement(),
            event_log,
            StubParentStore(),
            self.logger,
            None,
        )
        return runner, event_log

    def replayed_parameters(self, runner, event_log):
        """The parameters the parent comes back with when its recorded events are replayed.

        Args:
            runner (SyntheticOrder): The runner whose parent was changed.
            event_log (RecordingEventLog): The events recorded since it was built.

        Returns:
            dict: The replayed parameters.
        """
        events = [
            {
                'time': '2026-09-27T10:00:00+00:00',
                'parent_order_id': PARENT,
                'sequence': 1,
                'event': 'parent_received',
                'synthetic_type': runner.parent.synthetic_type,
                'parent_state': 'working',
                'instrument_id': INSTRUMENT,
                'detail': {
                    'body': runner.parent.body,
                    'parameters': {},
                },
            },
        ]
        events.extend(event_log.events)
        return ParentOrder.from_events(events).parameters

    def check_trailing_points(self):
        """A trailing stop whose trigger the caller loosened carries on from it.

        Returns:
            None: This method returns nothing.
        """
        runner, event_log = self.runner(
            'trailing_stop',
            {
                'trail_points': 10,
                'stop_limit_offset': 2,
                'watermark': '1000',
                'tick_size': '0.05',
            },
            [
                self.leg_event(1, 'stop', 'SELL', 10, 988, 990),
            ],
        )
        leg = runner.parent.legs[0]
        runner.apply_outside_modification(leg, None, decimal.Decimal('978'), decimal.Decimal('980'))
        watermark = decimal.Decimal(runner.parent.parameters.get('watermark'))
        replayed = decimal.Decimal(self.replayed_parameters(runner, event_log).get('watermark'))
        self.check(
            'a trailing stop moved to 980 trails from a watermark of 990',
            watermark == 990 and replayed == 990 and leg.trigger_price == 980.0,
            f'watermark {watermark}, after replay {replayed}, trigger {leg.trigger_price}',
        )

    def check_trailing_percent(self):
        """A percentage trail works back to the watermark whose trail lands on the caller's trigger.

        Returns:
            None: This method returns nothing.
        """
        runner, _ = self.runner(
            'trailing_stop',
            {
                'trail_percent': 1,
                'stop_limit_offset': 2,
                'watermark': '1010',
                'tick_size': '0.05',
            },
            [
                self.leg_event(1, 'stop', 'SELL', 10, 997, 999.9),
            ],
        )
        leg = runner.parent.legs[0]
        runner.apply_outside_modification(leg, None, decimal.Decimal('988'), decimal.Decimal('990'))
        watermark = decimal.Decimal(runner.parent.parameters.get('watermark'))
        self.check(
            'a one per cent trail moved to 990 trails from a watermark of 1000',
            watermark == decimal.Decimal('1000'),
            f'watermark {watermark}',
        )

    def check_chaser(self):
        """A chaser whose price the caller moved waits a full interval before its next step.

        Returns:
            None: This method returns nothing.
        """
        runner, _ = self.runner(
            'chaser',
            {
                'stepped_at': 0,
                'tick_size': '0.05',
            },
            [
                self.leg_event(1, 'entry', 'BUY', 10, 100),
            ],
        )
        before = time.time()
        runner.apply_outside_modification(runner.parent.legs[0], None, decimal.Decimal('100.5'), None)
        stepped_at = runner.parent.parameters.get('stepped_at')
        self.check(
            'a chaser moved by the caller restarts its step wait',
            isinstance(stepped_at, (int, float)) and stepped_at >= before - 1,
            f'stepped_at {stepped_at}',
        )

    def check_peg(self):
        """A peg whose price the caller set takes the offset from the best bid that puts it there.

        Returns:
            None: This method returns nothing.
        """
        quote = {
            'last_price': 100.1,
            'depth': {
                'buy': [
                    {
                        'price': 100.0,
                        'quantity': 50,
                        'orders': 2,
                    },
                ],
                'sell': [
                    {
                        'price': 100.1,
                        'quantity': 40,
                        'orders': 1,
                    },
                ],
            },
        }
        runner, event_log = self.runner(
            'peg',
            {
                'reference': 'own_touch',
                'offset_ticks': 0,
                'tick_size': '0.05',
            },
            [
                self.leg_event(1, 'entry', 'BUY', 10, 100),
            ],
            StubPlacement(quote),
        )
        runner.apply_outside_modification(runner.parent.legs[0], None, decimal.Decimal('99.8'), None)
        offset = runner.parent.parameters.get('offset_ticks')
        replayed = self.replayed_parameters(runner, event_log).get('offset_ticks')
        self.check(
            'a peg on the best bid of 100.00 moved to 99.80 sits four ticks away',
            offset == 4 and replayed == 4,
            f'offset_ticks {offset}, after replay {replayed}',
        )

    def check_linked_exits(self):
        """Reducing a bracket's stop reduces its target to match.

        Returns:
            None: This method returns nothing.
        """
        placement = StubPlacement()
        runner, _ = self.runner(
            'oco',
            {},
            [
                self.leg_event(1, 'stop', 'SELL', 10, 95, 96),
                self.leg_event(2, 'target', 'SELL', 10, 110),
            ],
            placement,
        )
        stop = runner.parent.legs[0]
        target = runner.parent.legs[1]
        runner.apply_outside_modification(stop, 6, None, None, 6)
        self.check(
            'an OCO stop reduced to 6 brings its target down to 6',
            stop.quantity == 6 and target.quantity == 6 and len(placement.changes) == 2,
            f'stop {stop.quantity}, target {target.quantity}, changes sent {placement.changes}',
        )
        problem = runner.outside_change_problem(stop, 12)
        self.check(
            'an exit of a linked pair cannot be raised',
            problem is not None and 'can only be reduced' in problem,
            f'refusal: {problem}',
        )

    def check_scale_out(self):
        """Reducing a scale-out's stop leaves its targets alone.

        Returns:
            None: This method returns nothing.
        """
        placement = StubPlacement()
        runner, _ = self.runner(
            'scale_out',
            {},
            [
                self.leg_event(1, 'stop', 'SELL', 10, 95, 96),
                self.leg_event(2, 'target', 'SELL', 5, 110),
                self.leg_event(3, 'target', 'SELL', 5, 120),
            ],
            placement,
        )
        runner.apply_outside_modification(runner.parent.legs[0], 8, None, None, 8)
        quantities = [leg.quantity for leg in runner.parent.legs]
        self.check(
            'a scale-out stop reduced to 8 leaves its targets as they were',
            quantities == [8, 5, 5] and len(placement.changes) == 1,
            f'quantities {quantities}',
        )

    def check_iceberg(self):
        """Cutting an iceberg's working slice returns the difference to what is still to place.

        Returns:
            None: This method returns nothing.
        """
        runner, event_log = self.runner(
            'iceberg',
            {
                'slice_quantity': 500,
                'placed_quantity': 500,
            },
            [
                self.leg_event(1, 'slice', 'BUY', 500, 100),
            ],
        )
        runner.apply_outside_modification(runner.parent.legs[0], 300, None, None, 300)
        placed = runner.parent.parameters.get('placed_quantity')
        replayed = self.replayed_parameters(runner, event_log).get('placed_quantity')
        self.check(
            'an iceberg slice cut from 500 to 300 counts 300 as placed',
            placed == 300 and replayed == 300,
            f'placed_quantity {placed}, after replay {replayed}',
        )

    def check_twap(self):
        """Cutting a TWAP slice carries the difference into the next slice.

        Returns:
            None: This method returns nothing.
        """
        runner, _ = self.runner(
            'twap',
            {
                'slice_count': 3,
                'interval_seconds': 60,
                'started_at': 0,
            },
            [
                self.leg_event(1, 'slice', 'BUY', 100, None),
            ],
        )
        runner.apply_outside_modification(runner.parent.legs[0], 60, None, None, 60)
        carried = runner.parent.parameters.get('carried_quantity')
        order = runner.read_order(runner.parent.body)
        next_slice = runner.slice_order(order, 3, 1)
        self.check(
            'a TWAP slice cut from 100 to 60 adds 40 to the next slice',
            carried == 40 and next_slice.quantity == 140 and runner.parent.parameters.get('carried_quantity') == 0,
            f'carried {carried}, next slice {next_slice.quantity}',
        )

    def run(self):
        """Runs every check.

        Returns:
            int: The exit code: 0 when every check passed, 1 otherwise.
        """
        self.check_trailing_points()
        self.check_trailing_percent()
        self.check_chaser()
        self.check_peg()
        self.check_linked_exits()
        self.check_scale_out()
        self.check_iceberg()
        self.check_twap()
        total = self.passed + len(self.failed)
        print(f'{self.passed}/{total} checks passed.')
        if self.failed:
            return 1
        return 0


if __name__ == '__main__':
    sys.exit(LegModificationChecks().run())
