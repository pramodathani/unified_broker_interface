"""One order an API worker has accepted and asked the order engine to place."""

import os
import socket
import time
import uuid

REPLY_KEY_PREFIX = 'unified:orders:intents:result:'


class OrderIntent:
    """An accepted order on its way to the order engine, and the key its answer comes back on.

    The caller's body is carried verbatim rather than as a re-serialised `PlaceOrderRequest`. `PlaceOrderRequest` reads no store and is deterministic, so the engine rebuilding it from the same body cannot reach a different result, and there is no second serialiser to drift from the first. The API worker validates only so that a malformed order is refused with HTTP 400 without costing a queue hop.

    Attributes:
        intent_id (str): This intent's id, which names the key the answer comes back on.
        created_at (float): The Unix time the intent was written.
        deadline_at (float): The Unix time after which the waiting API worker has given up.
        reply_key (str): The Redis list the engine pushes the answer onto.
        api_worker (str): The host and process that wrote the intent, for diagnosis.
        synthetic_type (str): The kind of order the engine is being asked to run, `simple` unless the body named another.
        instrument_id (str): The instrument the order is for, already resolved by the API worker.
        body (dict): The caller's decoded JSON body, exactly as it arrived.
    """

    def __init__(self, body, instrument_id, timeout_seconds):
        """Builds the intent for one accepted order.

        Args:
            body (dict | None): The caller's decoded JSON body, or None when there was none.
            instrument_id (str): The instrument the order is for, as the API worker resolved it.
            timeout_seconds (float): How long the API worker will wait for the answer, which sets the deadline.

        Returns:
            None: This method returns nothing.
        """
        self.intent_id = uuid.uuid4().hex
        self.instrument_id = instrument_id
        self.created_at = time.time()
        self.deadline_at = self.created_at + timeout_seconds
        self.reply_key = REPLY_KEY_PREFIX + self.intent_id
        self.api_worker = f'{socket.gethostname()}:{os.getpid()}'
        self.body = body if isinstance(body, dict) else {}
        self.synthetic_type = self.read_synthetic_type(self.body)

    def read_synthetic_type(self, body):
        """Reads which kind of order the body asks for.

        The value is carried but not checked here, because what a type needs beside it is the type's own business and is checked where the engine builds it.

        Args:
            body (dict): The caller's decoded JSON body.

        Returns:
            str: The named type, or `simple` when the body names none.
        """
        synthetic = body.get('synthetic')
        if isinstance(synthetic, dict):
            named_type = synthetic.get('type')
            if named_type:
                return str(named_type)
        return 'simple'

    def document(self):
        """The intent as the engine reads it off the stream.

        Returns:
            dict: The intent's fields, all of them JSON types.
        """
        return {
            'intent_id': self.intent_id,
            'created_at': self.created_at,
            'deadline_at': self.deadline_at,
            'reply_key': self.reply_key,
            'api_worker': self.api_worker,
            'synthetic_type': self.synthetic_type,
            'instrument_id': self.instrument_id,
            'body': self.body,
        }
