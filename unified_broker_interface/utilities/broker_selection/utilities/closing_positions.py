"""Which brokers already hold the positions an order would only reduce, so the order needs no new margin there."""

import datetime
import decimal
import json

POSITIONS_KEY = 'unified:portfolio:positions'
POSITIONS_TIME_FORMAT = '%Y-%m-%dT%H:%M:%S'

ORDER_PRODUCTS = {
    'CNC': 'delivery',
    'MIS': 'intraday',
    'NRML': 'carry',
}


class ClosingPositions:
    """Reads each broker's share of every open position from the unified positions document, and says whether an order only closes what a broker holds.

    A sell of an option the account already holds long frees margin rather than using it, but priced on its own it looks like writing a new option, which needs the underlying's value times its futures rate. Without this, every exit from a bought option was passed over at every broker that could not afford to write one, and refused with `no broker can take this order` while the position stayed open.

    The positions document is trusted only while it is fresh, and a broker's share only while that broker's positions are `ok`. When either is in doubt the order is priced as before, because treating an opening order as a closing one is the dangerous direction.

    Attributes:
        maximum_age_seconds (float): How old the positions document may be before it is ignored.
    """

    def __init__(self, maximum_age_seconds):
        """Builds the reader.

        Args:
            maximum_age_seconds (float): How old the positions document may be.

        Returns:
            None: This method returns nothing.
        """
        self.maximum_age_seconds = maximum_age_seconds

    def holdings(self, positions_text, now):
        """Each broker's signed quantity in every open position, from the unified positions document.

        Args:
            positions_text (str | bytes | None): The document as Redis holds it.
            now (datetime.datetime): The moment to judge the document's age by, as naive local time.

        Returns:
            dict: For each `(instrument_id, product)` tuple, the signed quantity (decimal.Decimal) each broker holds, by broker name; empty when the document is missing, unreadable or too old.
        """
        document = self.document(positions_text)
        if document is None:
            return {}
        written_at = self.read_time(document.get('as_of'))
        if written_at is None:
            return {}
        if (now - written_at).total_seconds() > self.maximum_age_seconds:
            return {}
        trusted_brokers = self.trusted_brokers(document)
        holdings = {}
        for position in document.get('net') or []:
            if not isinstance(position, dict):
                continue
            instrument_id = position.get('instrument_id')
            if not instrument_id:
                continue
            by_broker = position.get('by_broker')
            if not isinstance(by_broker, dict):
                continue
            key = (instrument_id, position.get('product'))
            held = holdings.setdefault(key, {})
            for broker_name, quantity in by_broker.items():
                if broker_name not in trusted_brokers:
                    continue
                units = self.decimal_or_zero(quantity)
                held[broker_name] = held.get(broker_name, decimal.Decimal(0)) + units
        return holdings

    def closes_only(self, holdings, legs, broker_name):
        """Whether every leg of an order only reduces a position the broker already holds, in the same instrument and product.

        Legs on the same instrument and product are taken one after another from what is held, so two sells cannot both count the same units.

        Args:
            holdings (dict): What `holdings` returned.
            legs (OrderLegs): The order's legs.
            broker_name (str): The broker.

        Returns:
            bool: True when every leg closes units the broker holds on the other side; False when any leg would open or add to a position.
        """
        remaining = {}
        for instrument_id, order in legs.legs:
            product = ORDER_PRODUCTS.get(order.product)
            if product is None:
                return False
            key = (instrument_id, product)
            if key not in remaining:
                held_by_broker = holdings.get(key) or {}
                remaining[key] = held_by_broker.get(broker_name, decimal.Decimal(0))
            held = remaining[key]
            quantity = decimal.Decimal(order.quantity)
            if order.transaction_type == 'SELL':
                if held < quantity:
                    return False
                remaining[key] = held - quantity
            elif order.transaction_type == 'BUY':
                if -held < quantity:
                    return False
                remaining[key] = held + quantity
            else:
                return False
        return True

    def document(self, positions_text):
        """The unified positions document, decoded.

        Args:
            positions_text (str | bytes | None): The document as Redis holds it.

        Returns:
            dict | None: The document, or None when it is missing or unreadable.
        """
        if isinstance(positions_text, bytes):
            positions_text = positions_text.decode('utf-8', 'replace')
        if not positions_text:
            return None
        try:
            document = json.loads(positions_text)
        except ValueError:
            return None
        if not isinstance(document, dict):
            return None
        return document

    def trusted_brokers(self, document):
        """The brokers whose positions the document read successfully and recently.

        Args:
            document (dict): The unified positions document.

        Returns:
            set: The broker names (str) whose status is `ok`.
        """
        trusted = set()
        for status in document.get('brokers') or []:
            if not isinstance(status, dict):
                continue
            if status.get('status') == 'ok' and status.get('broker'):
                trusted.add(status['broker'])
        return trusted

    @staticmethod
    def read_time(text):
        """When the positions document was written, from its `as_of`.

        Args:
            text (str | None): The time as `YYYY-MM-DDTHH:MM:SS` in local time.

        Returns:
            datetime.datetime | None: The time, or None when it cannot be read.
        """
        if not text:
            return None
        try:
            return datetime.datetime.strptime(text, POSITIONS_TIME_FORMAT)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def decimal_or_zero(value):
        """A quantity as a decimal, or zero when it cannot be read.

        Args:
            value (object): The quantity.

        Returns:
            decimal.Decimal: The quantity.
        """
        try:
            units = decimal.Decimal(str(value))
        except decimal.InvalidOperation:
            return decimal.Decimal(0)
        if not units.is_finite():
            return decimal.Decimal(0)
        return units
