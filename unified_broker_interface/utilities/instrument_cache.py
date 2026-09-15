"""Today's catalogue data for the instruments a worker has placed orders on, kept in that worker's memory."""

import datetime
import threading


class InstrumentCache:
    """The catalogue data `POST /api/orders/place` reads from Redis that does not change during a warm, kept in one worker's memory.

    Two things are kept: each instrument's identity and order handles, exactly as Redis held them, and which instrument a segment and identity-field prefix found.
    Everything is kept under a marker, the mapping date and warm identifier the data was read under, and is trusted only while the marker Redis holds is the same and it is still before the midnight after the data was first kept, when the catalogue keys expire.
    When either check fails everything is dropped, and the next order reads Redis again.
    Nothing is kept while Redis holds no warm identifier, because without one a re-run warm of the same date could not be told apart.

    Misses are never kept, because an instrument can be filled into the catalogue later in the day.

    Attributes:
        MAXIMUM_ENTRIES (int): The most instruments, and separately the most lookups, kept before that store is emptied.
        lock (threading.Lock): Guards every read and write, as a worker's threads share the cache.
        marker (tuple | None): The `(mapping date, warm identifier)` the kept data was read under, or None when nothing is kept.
        valid_until (datetime.datetime | None): The local midnight after which the kept data is dropped.
        instrument_texts (dict): Instrument ids to `(identity text, order handles text)`.
        instrument_lookups (dict): `(catalogue segment, catalogue prefix)` to the instrument id it found.
    """

    MAXIMUM_ENTRIES = 10000

    def __init__(self):
        """Builds an empty cache.

        Returns:
            None: This method returns nothing.
        """
        self.lock = threading.Lock()
        self.marker = None
        self.valid_until = None
        self.instrument_texts = {}
        self.instrument_lookups = {}

    def now(self):
        """The current local time.

        Returns:
            datetime.datetime: The time.
        """
        return datetime.datetime.now()

    def next_midnight(self, moment):
        """The local midnight that ends a moment's day.

        Args:
            moment (datetime.datetime): The moment.

        Returns:
            datetime.datetime: Midnight at the start of the following day.
        """
        following_day = moment.date() + datetime.timedelta(days=1)
        return datetime.datetime.combine(following_day, datetime.time())

    def current_marker(self, mapping_date_text, warm_identifier):
        """Brings the cache in line with the marker Redis holds, dropping everything kept under a different one or past midnight.

        The caller must hold `lock`.

        Args:
            mapping_date_text (str | None): `unified:catalogue:current_date` as Redis holds it.
            warm_identifier (str | None): `unified:catalogue:warm_identifier` as Redis holds it.

        Returns:
            bool: True when data may be read from and kept in the cache under this marker.
        """
        if not mapping_date_text or not warm_identifier:
            self.drop_everything()
            return False
        marker = (mapping_date_text, warm_identifier)
        now = self.now()
        if marker != self.marker or now >= self.valid_until:
            self.drop_everything()
            self.marker = marker
            self.valid_until = self.next_midnight(now)
        return True

    def drop_everything(self):
        """Forgets every kept instrument and lookup and the marker.

        The caller must hold `lock`.

        Returns:
            None: This method returns nothing.
        """
        self.marker = None
        self.valid_until = None
        self.instrument_texts = {}
        self.instrument_lookups = {}

    def instrument(self, mapping_date_text, warm_identifier, instrument_id):
        """Finds an instrument's identity and order handles.

        Args:
            mapping_date_text (str | None): The mapping date Redis holds now.
            warm_identifier (str | None): The warm identifier Redis holds now.
            instrument_id (str): The instrument id.

        Returns:
            tuple | None: `(identity text, order handles text)` as Redis held them, or None when they are not kept.
        """
        with self.lock:
            if not self.current_marker(mapping_date_text, warm_identifier):
                return None
            return self.instrument_texts.get(instrument_id)

    def keep_instrument(
        self,
        mapping_date_text,
        warm_identifier,
        instrument_id,
        identity_text,
        handles_text,
    ):
        """Keeps an instrument's identity and order handles, as read from Redis under the given marker.

        Args:
            mapping_date_text (str | None): The mapping date read in the same request.
            warm_identifier (str | None): The warm identifier read in the same request.
            instrument_id (str): The instrument id.
            identity_text (str): The identity as Redis held it.
            handles_text (str): The order handles as Redis held them.

        Returns:
            None: This method returns nothing.
        """
        with self.lock:
            if not self.current_marker(mapping_date_text, warm_identifier):
                return
            if len(self.instrument_texts) >= self.MAXIMUM_ENTRIES:
                self.instrument_texts = {}
            self.instrument_texts[instrument_id] = (identity_text, handles_text)

    def instrument_lookup(
        self,
        mapping_date_text,
        warm_identifier,
        catalogue_segment,
        catalogue_prefix,
    ):
        """Finds which instrument a segment and identity-field prefix found before.

        Args:
            mapping_date_text (str | None): The mapping date Redis holds now.
            warm_identifier (str | None): The warm identifier Redis holds now.
            catalogue_segment (str): The exchange-prefixed segment.
            catalogue_prefix (str): The catalogue member prefix.

        Returns:
            str | None: The instrument id, or None when the lookup is not kept.
        """
        with self.lock:
            if not self.current_marker(mapping_date_text, warm_identifier):
                return None
            return self.instrument_lookups.get(
                (catalogue_segment, catalogue_prefix),
            )

    def keep_instrument_lookup(
        self,
        mapping_date_text,
        warm_identifier,
        catalogue_segment,
        catalogue_prefix,
        instrument_id,
    ):
        """Keeps the one instrument a segment and identity-field prefix found in Redis.

        Args:
            mapping_date_text (str | None): The mapping date read in the same request.
            warm_identifier (str | None): The warm identifier read in the same request.
            catalogue_segment (str): The exchange-prefixed segment.
            catalogue_prefix (str): The catalogue member prefix.
            instrument_id (str): The instrument id it found.

        Returns:
            None: This method returns nothing.
        """
        with self.lock:
            if not self.current_marker(mapping_date_text, warm_identifier):
                return
            if len(self.instrument_lookups) >= self.MAXIMUM_ENTRIES:
                self.instrument_lookups = {}
            lookup_key = (catalogue_segment, catalogue_prefix)
            self.instrument_lookups[lookup_key] = instrument_id
