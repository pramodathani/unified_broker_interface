"""One order an API worker has accepted and asked the order engine to place."""

import os
import socket
import time
import uuid

REPLY_KEY_PREFIX = 'unified:orders:intents:result:'
HELD_TYPE = 'virtual_limit'


class OrderIntent:
    """An accepted order on its way to the order engine, and the key its answer comes back on.

    The caller's body is carried verbatim rather than as a re-serialised `PlaceOrderRequest`. `PlaceOrderRequest` reads no store and is deterministic, so the engine rebuilding it from the same body cannot reach a different result, and there is no second serialiser to drift from the first. The API worker validates only so that a malformed order is refused with HTTP 400 without costing a queue hop.

    Attributes:
        intent_id (str): This intent's id, which names the key the answer comes back on.
        created_at (float): The Unix time the intent was written.
        deadline_at (float): The Unix time after which the waiting API worker has given up.
        reply_key (str): The Redis list the engine pushes the answer onto.
        api_worker (str): The host and process that wrote the intent, for diagnosis.
        synthetic_type (str | None): The kind of order the engine is being asked to run, `simple` unless the body named another, or None for a command.
        instrument_id (str): The instrument the order is for, already resolved by the API worker.
        body (dict): The caller's decoded JSON body, exactly as it arrived.
        request_index (int | None): The order's place in the list it came in, or None for an order sent on its own.
        command (str | None): A change to a parent the engine owns, such as `cancel_leg`, with its arguments in `body`, or None for an order to place.
    """

    def __init__(
        self,
        body,
        instrument_id,
        timeout_seconds,
        request_index=None,
        reply_key=None,
        command=None,
        hold_limits=False,
    ):
        """Builds the intent for one accepted order.

        Args:
            body (dict | None): The caller's decoded JSON body, or None when there was none.
            instrument_id (str): The instrument the order is for, as the API worker resolved it.
            timeout_seconds (float): How long the API worker will wait for the answer, which sets the deadline.
            request_index (int | None): The order's place in the list it came in, or None for an order sent on its own.
            reply_key (str | None): The list every order of one request is answered on, or None for a list of this order's own.
            command (str | None): A change to a parent the engine owns, with its arguments in `body`, or None for an order to place.
            hold_limits (bool): Whether a plain limit order is held in the engine's virtual order book rather than sent at once.

        Returns:
            None: This method returns nothing.
        """
        self.intent_id = uuid.uuid4().hex
        self.instrument_id = instrument_id
        self.created_at = time.time()
        self.deadline_at = self.created_at + timeout_seconds
        self.request_index = request_index
        self.command = command
        self.reply_key = reply_key or (REPLY_KEY_PREFIX + self.intent_id)
        self.api_worker = f'{socket.gethostname()}:{os.getpid()}'
        self.body = body if isinstance(body, dict) else {}
        self.synthetic_type = None
        if command is None:
            self.synthetic_type = self.read_synthetic_type(self.body, hold_limits)

    def read_synthetic_type(self, body, hold_limits):
        """Reads which kind of order the body asks for.

        The value is carried but not checked here, because what a type needs beside it is the type's own business and is checked where the engine builds it.

        Args:
            body (dict): The caller's decoded JSON body.
            hold_limits (bool): Whether a plain limit order is held in the virtual order book.

        Returns:
            str: The named type; `virtual_limit` for a plain limit order when limits are held; `simple` otherwise.
        """
        synthetic = body.get('synthetic')
        if isinstance(synthetic, dict):
            named_type = synthetic.get('type')
            if named_type:
                return str(named_type)
        if hold_limits and self.is_holdable(body):
            return HELD_TYPE
        return 'simple'

    def is_holdable(self, body):
        """Whether an order that names no type is one the virtual order book can hold.

        Only a limit order with a price of its own is held. An `IOC` order asks to trade now or never, so holding it would change what it means, and a body with a `synthetic` object has chosen its type, `simple` included.

        Args:
            body (dict): The caller's decoded JSON body.

        Returns:
            bool: True when the order is held rather than sent at once.
        """
        if 'synthetic' in body:
            return False
        if str(body.get('order_type') or '').upper() != 'LIMIT':
            return False
        if body.get('price') is None:
            return False
        return str(body.get('validity') or 'DAY').upper() != 'IOC'

    def document(self):
        """The intent as the engine reads it off the stream.

        Returns:
            dict: The intent's fields, all of them JSON types.
        """
        document = {
            'intent_id': self.intent_id,
            'created_at': self.created_at,
            'deadline_at': self.deadline_at,
            'reply_key': self.reply_key,
            'api_worker': self.api_worker,
            'synthetic_type': self.synthetic_type,
            'instrument_id': self.instrument_id,
            'body': self.body,
        }
        if self.request_index is not None:
            document['request_index'] = self.request_index
        if self.command is not None:
            document['command'] = self.command
        return document
