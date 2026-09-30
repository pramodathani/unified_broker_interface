"""The interface every broker selection algorithm implements."""


class BrokerSelector:
    """Orders the brokers an order is offered to.

    One instance is built per gunicorn worker, when the order blueprint is built, and one per order engine. A subclass sets `NAME`, implements `ranked_brokers`, and overrides `queue_redis_commands` when it needs Redis, `passed_over_reason` when it can rule a broker out, `record_chosen` when it keeps track of its own choices and `record_outcome` when it learns from answers.

    Attributes:
        NAME (str): The name `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_SELECTOR` selects the algorithm by.
        cost_table (BrokerCostTable): Each broker's brokerage and order-rate limits, held in memory.
        margin_rate_table (MarginRateTable | None): The exchange's margin rates, for a selector that checks funds, or None.
    """

    NAME = None

    def __init__(self, cost_table, margin_rate_table=None):
        """Builds the selector.

        Args:
            cost_table (BrokerCostTable): Each broker's brokerage and order-rate limits.
            margin_rate_table (MarginRateTable | None): The exchange's margin rates, or None.

        Returns:
            None: This method returns nothing.
        """
        self.cost_table = cost_table
        self.margin_rate_table = margin_rate_table

    def queue_redis_commands(self, pipeline, order, instrument_id, legs=None):
        """Queues the Redis commands the selector needs on the pipeline that also reads the instrument.

        The commands run after the order has been validated and before the instrument is known, in the same round trip as the instrument's identity and order handles.

        Args:
            pipeline (redis.client.Pipeline): The pipeline to queue commands on.
            order (PlaceOrderRequest): The validated order.
            instrument_id (str): The instrument's id.
            legs (OrderLegs | None): Every leg of a strategy this order is the first of, or None for a single order.

        Returns:
            int: How many commands were queued, whose replies are handed to `ranked_brokers` in the same order.
        """
        del pipeline
        del order
        del instrument_id
        del legs
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

    def passed_over_reason(self, broker_name):
        """Why this selector rules a broker out for the order it last ranked on this thread, or None.

        The placement asks this for each broker it is about to offer the order to, after the broker's own checks have passed.

        Args:
            broker_name (str): The broker.

        Returns:
            str | None: The reason, or None when the selector does not rule the broker out.
        """
        del broker_name
        return None

    def record_passed_over(self, cache, passed_over):
        """Learns that the chosen broker came after some that could not take the order.

        Args:
            cache (redis.Redis): The Redis client.
            passed_over (int): How many brokers were passed over before the chosen one.

        Returns:
            None: This method returns nothing.
        """
        del cache
        del passed_over

    def record_chosen(self, broker_name):
        """Learns which broker this selector's ranking led to, in this process's memory only.

        It is called once the broker has been chosen and before anything is sent, so it must be quick and must read and write no store.

        Args:
            broker_name (str): The broker chosen.

        Returns:
            None: This method returns nothing.
        """
        del broker_name

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
