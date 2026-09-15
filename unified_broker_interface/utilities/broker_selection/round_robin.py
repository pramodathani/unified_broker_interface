"""The brokers take turns, with the turn kept in Redis so every worker shares it."""

from unified_broker_interface.utilities.broker_selection.base import (
    BrokerSelector,
)


class RoundRobinSelector(BrokerSelector):
    """Offers each order first to the broker after the one offered the previous order.

    The turn is `INCR unified:orders:round_robin` modulo the number of brokers in the rotation. When the broker whose turn it is cannot take the order, the next broker in the rotation is tried, so the broker after a skipped one takes two turns in a row.

    Attributes:
        COUNTER_KEY (str): The Redis key holding the turn counter.
    """

    NAME = 'round_robin'
    COUNTER_KEY = 'unified:orders:round_robin'

    def queue_redis_commands(self, pipeline, order, instrument_id):
        """Queues the increment of the turn counter.

        Args:
            pipeline (redis.client.Pipeline): The pipeline to queue the command on.
            order (PlaceOrderRequest): The validated order.
            instrument_id (str): The instrument's id.

        Returns:
            int: 1, for the one command queued.
        """
        del order
        del instrument_id
        pipeline.incr(self.COUNTER_KEY)
        return 1

    def ranked_brokers(self, order, instrument, rotation, redis_replies):
        """Lists the rotation starting at the broker whose turn it is.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            rotation (list): The broker names not excluded, in turn order.
            redis_replies (list): The counter after this order's increment, as the only reply.

        Returns:
            list: The rotation, rotated to start at the broker whose turn it is.
        """
        del order
        del instrument
        round_robin_counter = redis_replies[0]
        start_index = round_robin_counter % len(rotation)
        ranked = []
        for offset in range(len(rotation)):
            ranked.append(rotation[(start_index + offset) % len(rotation)])
        return ranked
