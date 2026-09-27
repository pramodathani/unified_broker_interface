"""Narrowing the day's order book or trade book to what a caller asked for, one page at a time.

`GET /api/orders/details` and `GET /api/orders/trades` serve one document holding the whole day. A caller who placed two hundred orders through a list, and wants to see only those, filters it with query parameters instead of downloading every order of the day and searching it.
"""

FINISHED_STATUSES = (
    'COMPLETE',
    'CANCELLED',
    'REJECTED',
    'EXPIRED',
)
MAXIMUM_LIMIT = 10000


class OrderBookFilterError(ValueError):
    """A filter parameter that cannot be read."""


class OrderBookFilter:
    """The filters and page a caller asked for, read from the query string.

    Every filter narrows the list; several together must all match. With none given, the document is served unchanged, exactly as it was before filters existed.

    Attributes:
        order_ids (set): Order ids to keep, from `order_id`, given more than once or comma-separated.
        parent_id (str | None): The order engine parent whose orders to keep.
        intent_id (str | None): The intent whose orders to keep.
        broker (str | None): The broker whose orders to keep.
        status (str | None): `open` for orders not yet finished, or one status such as `COMPLETE`.
        limit (int | None): The most entries to return.
        cursor (int): How many matching entries to skip, as a previous page's `next_cursor` gave it.
    """

    def __init__(self, query_arguments):
        """Reads the filters from the query string.

        Args:
            query_arguments (werkzeug.datastructures.MultiDict): The query string arguments.

        Returns:
            None: This method returns nothing.

        Raises:
            OrderBookFilterError: When `limit` or `cursor` is not a whole number in range.
        """
        self.order_ids = set()
        for value in query_arguments.getlist('order_id'):
            for part in value.split(','):
                if part.strip():
                    self.order_ids.add(part.strip())
        self.parent_id = query_arguments.get('parent_id') or None
        self.intent_id = query_arguments.get('intent_id') or None
        self.broker = query_arguments.get('broker') or None
        status = query_arguments.get('status') or None
        self.status = None
        if status is not None and status.lower() == 'open':
            self.status = 'open'
        elif status is not None:
            self.status = status.upper()
        self.limit = self.whole_number(query_arguments.get('limit'), 'limit', 1, MAXIMUM_LIMIT)
        cursor = self.whole_number(query_arguments.get('cursor'), 'cursor', 0, None)
        self.cursor = cursor or 0

    def whole_number(self, text, name, lowest, highest):
        """Reads one whole-number parameter.

        Args:
            text (str | None): The parameter as given.
            name (str): Its name, for the message.
            lowest (int): The smallest value allowed.
            highest (int | None): The largest value allowed, or None for no limit.

        Returns:
            int | None: The number, or None when the parameter was not given.

        Raises:
            OrderBookFilterError: When it is not a whole number in range.
        """
        if text is None or text == '':
            return None
        try:
            number = int(text)
        except ValueError:
            raise OrderBookFilterError(f'{name} must be a whole number, not {text!r}')
        if number < lowest or (highest is not None and number > highest):
            if highest is None:
                raise OrderBookFilterError(f'{name} must be at least {lowest}, not {number}')
            raise OrderBookFilterError(f'{name} must be from {lowest} to {highest}, not {number}')
        return number

    def is_active(self):
        """Whether the caller asked for anything but the whole document.

        Returns:
            bool: True when a filter or a page was given.
        """
        return bool(
            self.order_ids
            or self.parent_id
            or self.intent_id
            or self.broker
            or self.status
            or self.limit is not None
            or self.cursor
        )

    def matches(self, entry):
        """Whether one order or trade passes every filter.

        Args:
            entry (dict): One order or trade.

        Returns:
            bool: True when it is kept.
        """
        if self.order_ids and str(entry.get('order_id')) not in self.order_ids:
            return False
        if self.parent_id and entry.get('engine_parent_id') != self.parent_id:
            return False
        if self.intent_id and entry.get('intent_id') != self.intent_id:
            return False
        if self.broker and entry.get('broker') != self.broker:
            return False
        if self.status == 'open':
            return str(entry.get('status') or '').upper() not in FINISHED_STATUSES
        if self.status and str(entry.get('status') or '').upper() != self.status:
            return False
        return True

    def apply(self, document, list_name):
        """The document with its list narrowed to the matching entries of the asked-for page.

        The day's `summary` and `brokers` are kept as they are, and a `page` object says how many entries matched, how many are returned, and the cursor for the next page, which is None on the last one.

        Args:
            document (dict): The day's document, as served unfiltered.
            list_name (str): The list to narrow, `orders` or `trades`.

        Returns:
            dict: A new document.
        """
        matching = []
        for entry in document.get(list_name) or []:
            if self.matches(entry):
                matching.append(entry)
        end = len(matching)
        if self.limit is not None:
            end = min(end, self.cursor + self.limit)
        page = matching[self.cursor:end]
        next_cursor = None
        if end < len(matching):
            next_cursor = end
        narrowed = dict(document)
        narrowed[list_name] = page
        narrowed['page'] = {
            'matched': len(matching),
            'returned': len(page),
            'cursor': self.cursor,
            'next_cursor': next_cursor,
        }
        return narrowed
