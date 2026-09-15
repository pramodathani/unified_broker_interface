"""The interface every broker selection algorithm implements."""


class BrokerSelector:
    """Orders the brokers an order is offered to.

    One instance is built per gunicorn worker, when the order blueprint is built. A subclass sets `NAME`, implements `ranked_brokers`, and overrides `queue_redis_commands` when it needs Redis and `record_outcome` when it learns from answers.

    Attributes:
        NAME (str): The name `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_SELECTOR` selects the algorithm by.
    """

    NAME = None

    def queue_redis_commands(self, pipeline, order, instrument_id):
        """Queues the Redis commands the selector needs on the pipeline that also reads the instrument.

        The commands run after the order has been validated and before the instrument is known, in the same round trip as the instrument's identity and order handles.

        Args:
            pipeline (redis.client.Pipeline): The pipeline to queue commands on.
            order (PlaceOrderRequest): The validated order.
            instrument_id (str): The instrument's id.

        Returns:
            int: How many commands were queued, whose replies are handed to `ranked_brokers` in the same order.
        """
        del pipeline
        del order
        del instrument_id
        return 0

    def ranked_brokers(self, order, instrument, rotation, redis_replies):
        """Orders the brokers the order is offered to; the first that can take it gets it.

        Args:
            order (PlaceOrderRequest): The validated order.
            instrument (Instrument): The tradeable instrument.
            rotation (list): The broker names not excluded by configuration, in turn order.
            redis_replies (list): The replies to the commands `queue_redis_commands` queued, in order.

        Returns:
            list: Broker names from `rotation`, in the order to try them. A name that is not in `rotation` is ignored.

        Raises:
            NotImplementedError: Always, in the base class.
        """
        raise NotImplementedError

    def record_outcome(self, broker_name, answer):
        """Learns from a sent order's answer, in this worker's memory only.

        It is called after the broker has answered and before the route answers, so it must be quick and must read and write no store. An exception it raises is logged and does not change the route's answer.

        Args:
            broker_name (str): The broker the order was sent to.
            answer (BrokerAnswer): The broker's answer.

        Returns:
            None: This method returns nothing.
        """
        del broker_name
        del answer
