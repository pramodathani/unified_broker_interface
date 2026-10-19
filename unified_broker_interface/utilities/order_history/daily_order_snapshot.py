"""Saves every broker's orders of one day, as `unified:orders:orders` last holds them, to `unified.daily_orders`."""

import datetime
import decimal
import json

from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    INDIA,
)
from unified_broker_interface.utilities.order_engine.utilities.synthetic_order_event_log import (
    DDL_DIRECTORY,
)

DDL_FILE = '370_unified_daily_orders.sql'
DOCUMENT_KEY = 'unified:orders:orders'

ROW_COLUMNS = [
    'trading_day',
    'broker',
    'order_id',
    'exchange_order_id',
    'engine_parent_id',
    'leg_role',
    'status',
    'status_message',
    'instrument_id',
    'tradingsymbol',
    'exchange',
    'transaction_type',
    'product',
    'order_type',
    'quantity',
    'filled_quantity',
    'price',
    'trigger_price',
    'average_price',
    'order_timestamp',
    'exchange_timestamp',
    'order',
]

DELETE_QUERY = """
DELETE FROM unified.daily_orders
WHERE trading_day = %s
"""


class DailyOrderSnapshot:
    """One day's orders at every broker, in their final state, taken from the combined orders document before it expires.

    `bin/unified/orders/api_order_details` keeps `unified:orders:orders` current from every broker's order hash, polled or streamed, and Redis drops it at the next 06:00 IST. A snapshot taken late in the evening therefore holds each order of the day as it ended: its status, its filled quantity and its average price. That is the only lasting record of a Flattrade order, because Flattrade's orders are polled and never streamed, and it is how a stop that filled at the broker while it was being cancelled, so that the order engine never saw the fill, can still be priced.

    Attributes:
        cache (redis.Redis): The Redis connection the document is read from.
        connect (Callable): Opens a PostgreSQL connection, such as `configurations.get_postgres`.
        logger (logging.Logger): The logger.
    """

    def __init__(self, cache, connect, logger):
        """Builds the snapshot.

        Args:
            cache (redis.Redis): The Redis connection.
            connect (Callable): Opens a PostgreSQL connection.
            logger (logging.Logger): The logger.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.connect = connect
        self.logger = logger

    def read_document(self):
        """Reads the combined orders document.

        Returns:
            dict | None: The document, or None when Redis holds none.

        Raises:
            redis.exceptions.RedisError: When Redis cannot be read.
            json.JSONDecodeError: When the document is not JSON.
        """
        raw = self.cache.get(DOCUMENT_KEY)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        return json.loads(raw)

    def trading_day_of(self, order):
        """The day in India an order was placed on.

        Args:
            order (dict): One order of the document.

        Returns:
            datetime.date | None: The day of its `order_timestamp`, or None when it has none.
        """
        moment = self.moment(order.get('order_timestamp'))
        if moment is None:
            return None
        return moment.astimezone(INDIA).date()

    def trading_days(self, document):
        """The days the document's orders were placed on.

        Args:
            document (dict | None): The combined orders document.

        Returns:
            list: The days (datetime.date), earliest first; usually one, because the document empties at 06:00 IST.
        """
        days = []
        if not document:
            return days
        for order in document.get('orders') or []:
            trading_day = self.trading_day_of(order)
            if trading_day is not None and trading_day not in days:
                days.append(trading_day)
        days.sort()
        return days

    def orders_of_day(self, document, trading_day):
        """The orders of the document placed on one day.

        Args:
            document (dict | None): The combined orders document.
            trading_day (datetime.date): The day.

        Returns:
            list: The orders (dict) placed that day, in the document's order.
        """
        if not document:
            return []
        kept = []
        for order in document.get('orders') or []:
            if self.trading_day_of(order) == trading_day:
                kept.append(order)
        return kept

    def moment(self, value):
        """Reads an ISO timestamp.

        Args:
            value (str | None): The timestamp, such as `2026-10-19T13:17:41+05:30`.

        Returns:
            datetime.datetime | None: The moment, or None when there is none or it cannot be read.
        """
        if not value:
            return None
        try:
            return datetime.datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    def number(self, value):
        """Reads a price for a NUMERIC column.

        Args:
            value (float | int | str | None): The price.

        Returns:
            decimal.Decimal | None: The price, or None when there is none or it is not a number.
        """
        if value is None or value == '':
            return None
        try:
            return decimal.Decimal(str(value))
        except decimal.InvalidOperation:
            return None

    def whole(self, value):
        """Reads a quantity for a BIGINT column.

        Args:
            value (float | int | str | None): The quantity.

        Returns:
            int | None: The quantity rounded to a whole number, or None when there is none or it is not a number.
        """
        number = self.number(value)
        if number is None:
            return None
        return int(number.to_integral_value())

    def row(self, order, trading_day):
        """One order as a row of `unified.daily_orders`.

        Args:
            order (dict): One order of the document.
            trading_day (datetime.date): The day it belongs to.

        Returns:
            dict: One value per name in `ROW_COLUMNS`; `order` is the whole order as JSON text.
        """
        return {
            'trading_day': trading_day,
            'broker': order.get('broker'),
            'order_id': str(order.get('order_id')),
            'exchange_order_id': order.get('exchange_order_id'),
            'engine_parent_id': order.get('engine_parent_id'),
            'leg_role': order.get('leg_role'),
            'status': order.get('status'),
            'status_message': order.get('status_message'),
            'instrument_id': order.get('instrument_id'),
            'tradingsymbol': order.get('tradingsymbol'),
            'exchange': order.get('exchange'),
            'transaction_type': order.get('transaction_type'),
            'product': order.get('product'),
            'order_type': order.get('order_type'),
            'quantity': self.whole(order.get('quantity')),
            'filled_quantity': self.whole(order.get('filled_quantity')),
            'price': self.number(order.get('price')),
            'trigger_price': self.number(order.get('trigger_price')),
            'average_price': self.number(order.get('average_price')),
            'order_timestamp': self.moment(order.get('order_timestamp')),
            'exchange_timestamp': self.moment(order.get('exchange_timestamp')),
            'order': json.dumps(order),
        }

    def write(self, trading_day, orders):
        """Replaces the day's rows with the orders given, in one transaction, creating the table first if it is missing.

        Args:
            trading_day (datetime.date): The day.
            orders (list): The day's orders (dict).

        Returns:
            int: How many rows were written.

        Raises:
            psycopg2.Error: When the database cannot be written, after rolling back.
        """
        placeholders = ', '.join(['%s'] * len(ROW_COLUMNS))
        quoted = []
        for column in ROW_COLUMNS:
            quoted.append(f'"{column}"')
        insert = (
            f'INSERT INTO unified.daily_orders ({", ".join(quoted)}) '
            f'VALUES ({placeholders}) '
            'ON CONFLICT (trading_day, broker, order_id) DO NOTHING'
        )
        values = []
        for order in orders:
            row = self.row(order, trading_day)
            row_values = []
            for column in ROW_COLUMNS:
                row_values.append(row[column])
            values.append(row_values)
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute((DDL_DIRECTORY / DDL_FILE).read_text())
                cursor.execute(DELETE_QUERY, (trading_day,))
                if values:
                    cursor.executemany(insert, values)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return len(values)

    def summary(self, orders):
        """One line of figures per broker.

        Args:
            orders (list): The day's orders (dict).

        Returns:
            list: Dicts with `broker`, `orders`, `filled` (orders with a fill) and `filled_value` (decimal.Decimal, filled quantity times average price), sorted by broker.
        """
        lines = {}
        for order in orders:
            broker = order.get('broker') or ''
            line = lines.get(broker)
            if line is None:
                line = {
                    'broker': broker,
                    'orders': 0,
                    'filled': 0,
                    'filled_value': decimal.Decimal(0),
                }
                lines[broker] = line
            line['orders'] = line['orders'] + 1
            filled = self.whole(order.get('filled_quantity')) or 0
            price = self.number(order.get('average_price'))
            if filled > 0 and price is not None:
                line['filled'] = line['filled'] + 1
                line['filled_value'] = line['filled_value'] + filled * price
        result = []
        for broker in sorted(lines):
            result.append(lines[broker])
        return result
