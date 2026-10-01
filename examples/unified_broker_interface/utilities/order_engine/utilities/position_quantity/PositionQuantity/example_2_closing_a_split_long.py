"""Closes a long of 75 RELIANCE held as 50 at Flattrade and 25 at Zerodha, after cancelling an order resting on it.

`PositionQuantity.close` reads every broker's positions through `PositionCloser`, cancels the orders resting on the instrument first, and sends each broker's share to that broker as a sell two ticks under the bid. The stand-ins below play Redis and the plan order and note every request, so nothing leaves the machine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/position_quantity/PositionQuantity/example_2_closing_a_split_long.py
"""

import decimal
import json
import logging

from unified_broker_interface.utilities.order_engine.utilities.position_quantity import (
    PositionQuantity,
)

RELIANCE = '11111111-1111-5111-8111-000000000001'


class StandInPipeline:
    """Stands in for a Redis pipeline that only reads hashes.

    Attributes:
        cache (StandInCache): The cache it reads.
        keys (list): The hashes asked for, in order.
    """

    def __init__(self, cache):
        """Builds the pipeline.

        Args:
            cache (StandInCache): The cache it reads.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.keys = []

    def hgetall(self, key):
        """Queues a hash to read.

        Args:
            key (str): The hash.

        Returns:
            None: This method returns nothing.
        """
        self.keys.append(key)

    def execute(self):
        """Reads every queued hash.

        Returns:
            list: Each hash, in order.
        """
        replies = []
        for key in self.keys:
            replies.append(self.cache.hgetall(key))
        return replies


class StandInCache:
    """Stands in for Redis, holding each broker's positions, the broker tokens and one resting order.

    Attributes:
        hashes (dict): Each hash by key.
    """

    def __init__(self):
        """Builds the cache.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = {
            'unified:broker_tokens': {
                'flattrade:2885': json.dumps([RELIANCE]),
                'zerodha:2885': json.dumps([RELIANCE]),
            },
            'unified:order-updates': {
                '26091500000077': json.dumps({
                    'instrument_id': RELIANCE,
                    'status': 'OPEN',
                    'broker': 'flattrade',
                    'order_id': '26091500000077',
                }),
            },
        }
        for broker_name, quantity in (('flattrade', 50), ('zerodha', 25)):
            self.hashes[f'{broker_name}:portfolio:positions'] = {
                'NET:NSE:2885:MIS': json.dumps({
                    'position': {
                        'instrument_token': '2885',
                        'tradingsymbol': 'RELIANCE-EQ',
                        'exchange': 'NSE',
                        'product': 'MIS',
                        'quantity': quantity,
                        'day_or_net': 'NET',
                    },
                }),
            }

    def pipeline(self, transaction):
        """A pipeline over this cache.

        Args:
            transaction (bool): Unused.

        Returns:
            StandInPipeline: The pipeline.
        """
        del transaction
        return StandInPipeline(self)

    def hgetall(self, key):
        """One hash.

        Args:
            key (str): The hash.

        Returns:
            dict: Its fields.
        """
        return self.hashes.get(key, {})

    def hget(self, key, field):
        """One field of a hash.

        Args:
            key (str): The hash.
            field (str): The field.

        Returns:
            str | None: The value.
        """
        return self.hashes.get(key, {}).get(field)


class StandInInstrument:
    """Stands in for an instrument in the catalogue.

    Attributes:
        handles (dict): Each broker's handle, unused here.
    """

    def __init__(self):
        """Builds the instrument.

        Returns:
            None: This method returns nothing.
        """
        self.handles = {}


class StandInOrderPlacement:
    """Stands in for the order placement, naming the brokers.

    Attributes:
        broker_names (list): The brokers.
    """

    def __init__(self):
        """Builds the placement.

        Returns:
            None: This method returns nothing.
        """
        self.broker_names = [
            'flattrade',
            'zerodha',
        ]


class StandInPlacement:
    """Stands in for the engine's placement: the cache, the brokers and the live quote.

    Attributes:
        cache (StandInCache): The cache.
        order_placement (StandInOrderPlacement): The brokers.
    """

    def __init__(self):
        """Builds the placement.

        Returns:
            None: This method returns nothing.
        """
        self.cache = StandInCache()
        self.order_placement = StandInOrderPlacement()

    def market_context(self, instrument_id, with_quote, with_depth):
        """The instrument and its live quote, with the bid at 994.90 and the offer at 994.95.

        Args:
            instrument_id (str): Unused.
            with_quote (bool): Unused.
            with_depth (bool): Unused.

        Returns:
            tuple: The instrument, the quote and an unused value.
        """
        del instrument_id, with_quote, with_depth
        quote = {
            'last_price': 994.95,
            'depth': {
                'buy': [
                    {
                        'price': 994.90,
                        'quantity': 100,
                    },
                ],
                'sell': [
                    {
                        'price': 994.95,
                        'quantity': 100,
                    },
                ],
            },
        }
        return StandInInstrument(), quote, None


class StandInOrder:
    """Stands in for a validated order.

    Attributes:
        body (dict): The body.
    """

    def __init__(self, body):
        """Builds the order.

        Args:
            body (dict): The body.

        Returns:
            None: This method returns nothing.
        """
        self.body = body

    def agreed_tick_size(self, handles):
        """The tick size the brokers agree on.

        Args:
            handles (dict): Unused.

        Returns:
            decimal.Decimal: 0.05.
        """
        del handles
        return decimal.Decimal('0.05')


class StandInParent:
    """Stands in for the plan order's parent.

    Attributes:
        body (dict): The caller's body, an intraday buy.
    """

    def __init__(self):
        """Builds the parent.

        Returns:
            None: This method returns nothing.
        """
        self.body = {
            'transaction_type': 'BUY',
            'product': 'MIS',
            'quantity': 75,
        }


class StandInPlanOrder:
    """Stands in for the plan order, noting every cancel and order.

    Attributes:
        parent (StandInParent): The parent.
        placement (StandInPlacement): The placement.
        logger (logging.Logger): The logger.
        requests (list): Every request, in order.
    """

    def __init__(self):
        """Builds the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.parent = StandInParent()
        self.placement = StandInPlacement()
        self.logger = logging.getLogger('example')
        self.requests = []

    def read_order(self, body):
        """The body as an order.

        Args:
            body (dict): The body.

        Returns:
            StandInOrder: The order.
        """
        return StandInOrder(body)

    def cancel_outside_order(self, broker_name, broker_order_id, reason):
        """Notes a cancel of an order the engine did not place.

        Args:
            broker_name (str): The broker.
            broker_order_id (str): The order.
            reason (str): Why.

        Returns:
            bool: True.
        """
        self.requests.append(f'cancel {broker_order_id} at {broker_name}: {reason}')
        return True

    def place_leg(self, role, order, started_at, broker_name, instrument_id):
        """Notes a closing order.

        Args:
            role (str): The leg's role.
            order (StandInOrder): The order.
            started_at (float | None): Unused.
            broker_name (str): The broker.
            instrument_id (str): The instrument.

        Returns:
            tuple: An answer, its status and no leg.
        """
        del started_at
        self.requests.append(f'{role}: {order.body["transaction_type"]} {order.body["quantity"]} at {order.body["price"]} at {broker_name}, {instrument_id == RELIANCE}')
        return {'outcome': 'accepted'}, 200, None


class StandInContext:
    """Stands in for the order's view of the plan order.

    Attributes:
        instrument_id (str): The order's instrument.
        body (dict): The order's body.
    """

    def __init__(self):
        """Builds the context.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = RELIANCE
        self.body = {
            'product': 'MIS',
        }


class ClosingASplitLongExample:
    """Closes a split long and prints every request."""

    def run(self):
        """Prints what was found and sent.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        quantity = PositionQuantity(None, None, False, 1, True)
        placed, found, cancelled = quantity.close(plan_order, StandInContext(), 'root')
        print(f'Found {found} positions, cancelled {cancelled} resting orders, placed {len(placed)} closing orders')
        for request in plan_order.requests:
            print(f'  {request}')


if __name__ == '__main__':
    ClosingASplitLongExample().run()
