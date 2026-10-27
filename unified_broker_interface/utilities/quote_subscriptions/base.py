"""The class every broker's quote subscription spelling subclasses."""


class BrokerQuoteSubscription:
    """Spells one broker's mapping rows the way that broker's quote websocket subscribes them.

    A subclass sets `BROKER_NAME` and implements `member`, which answers None for an instrument the broker's quote feed cannot stream, so the allocation passes that broker over for it.

    Attributes:
        BROKER_NAME (str): The broker, as the code spells it.
        cache (redis.Redis): The Redis client, for a broker whose spelling needs its instrument master.
    """

    BROKER_NAME = None

    def __init__(self, cache):
        """Keeps the Redis client.

        Args:
            cache (redis.Redis): The Redis client.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache

    def member(self, identity, broker_token, order_symbol):
        """The instrument as a member of the broker's subscription set.

        Args:
            identity (dict): The unified instrument's row from `unified.instruments`, with a canonical `exchange`, a prefixed `segment` and a `shape`.
            broker_token (str): The broker's token for the instrument, from `unified.broker_mappings`.
            order_symbol (str | None): The broker's order symbol for the instrument, from `unified.broker_mappings`.

        Returns:
            str | None: The member, or None when the broker's quote feed cannot stream the instrument.

        Raises:
            NotImplementedError: Always, until a subclass implements it.
        """
        raise NotImplementedError
