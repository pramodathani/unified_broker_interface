"""Telling an instrument that is not mapped apart from a catalogue that is not in Redis at all."""

import redis

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)

NOT_MAPPED_MESSAGE = 'the instrument is not mapped'
CURRENT_DATE_KEY = 'unified:catalogue:current_date'


class CatalogueAvailability:
    """A check that turns a misleading "not mapped" refusal into an honest one when the whole catalogue is missing.

    The catalogue keys for a mapping date expire at the midnight after they were written, but `unified:catalogue:current_date` keeps naming that date until the next morning's mapping publishes a new one. In that gap every instrument looks unmapped. This check runs only after an order has already been refused as not mapped, so an order that succeeds pays nothing for it.

    Attributes:
        cache (redis.Redis): The Redis client.
    """

    def __init__(self, cache):
        """Builds the check.

        Args:
            cache (redis.Redis): The Redis client.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache

    def explained(self, refusal):
        """Returns the refusal to answer with, replacing a "not mapped" refusal when the catalogue itself is missing.

        Args:
            refusal (RefusedRequestError): The refusal the order was answered with.

        Returns:
            RefusedRequestError: The same refusal, or a refusal with HTTP 503 saying that today's catalogue is not published yet.
        """
        if refusal.status != 404:
            return refusal
        if refusal.body.get('error') != NOT_MAPPED_MESSAGE:
            return refusal
        try:
            mapping_date_text = self.cache.get(CURRENT_DATE_KEY)
            if not mapping_date_text:
                return refusal
            identity_key = f'unified:catalogue:{mapping_date_text}:identity'
            catalogue_exists = self.cache.exists(identity_key)
        except redis.RedisError:
            return refusal
        if catalogue_exists:
            return refusal
        message = (
            f"today's instrument catalogue is not published yet: the catalogue for {mapping_date_text} has expired, and the daily mapping has not published a new one"
        )
        return RefusedRequestError.refusal(message, 503)
