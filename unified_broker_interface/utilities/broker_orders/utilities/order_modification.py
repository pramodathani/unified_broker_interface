"""An open order with a caller's changes laid over it, in the terms a broker's modify request is built from."""

import copy
import decimal

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    OrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.stored_order import (
    OrderNotReadyError,
)


class UnmodifiableOrderError(Exception):
    """A stored order that the modify route does not change, such as one whose product or validity is outside the route's words; its message is answered with HTTP 409."""


class OrderModification:
    """The order a modify request is built from: the stored normalized order, with every field the caller gave put in its place.

    Building one reads nothing but the stored order and the request, so every check here costs no I/O. The quantities stay in the broker's own terms as the order scripts stored them until the blueprint converts a changed quantity and calls `with_quantities`.

    Attributes:
        ORDER_TYPES (list): The order types the route handles.
        VALIDITIES (list): The validities the route handles.
        PRODUCTS (list): The products the route handles.
        TRANSACTION_TYPES (list): The transaction types the route handles.
        changed_fields (list): The names of the fields the caller gave.
        transaction_type (str): `BUY` or `SELL`, as stored.
        product (str): `CNC`, `MIS` or `NRML`, as stored.
        exchange (str | None): The broker's own exchange or segment code, as stored.
        tradingsymbol (str | None): The broker's trading symbol, as stored.
        instrument_token (str | None): The broker's instrument token as text, as stored, or None.
        order_type (str): The order type after the change.
        validity (str): The validity after the change.
        quantity (int): The total quantity in the broker's own terms.
        disclosed_quantity (int): The disclosed quantity in the broker's own terms, 0 when there is none.
        price (decimal.Decimal | None): The limit price after the change, or None when the order type takes none.
        trigger_price (decimal.Decimal | None): The trigger price after the change, or None when the order type takes none.
        price_text (str): The price as text, `0` when there is none.
        trigger_price_text (str): The trigger price as text, `0` when there is none.
        price_number (float): The price as a float, 0.0 when there is none.
        trigger_price_number (float): The trigger price as a float, 0.0 when there is none.
        tag (str | None): The order's tag, as stored.
    """

    ORDER_TYPES = [
        'MARKET',
        'LIMIT',
        'SL',
        'SL-M',
    ]

    VALIDITIES = [
        'DAY',
        'IOC',
    ]

    PRODUCTS = [
        'CNC',
        'MIS',
        'NRML',
    ]

    TRANSACTION_TYPES = [
        'BUY',
        'SELL',
    ]

    def __init__(self, modify_request, stored_order):
        """Lays the caller's changes over the stored order.

        Args:
            modify_request (ModifyOrderRequest): The validated modification.
            stored_order (StoredOrder): The order as the broker's order scripts keep it in Redis.

        Returns:
            None: This method returns nothing.

        Raises:
            UnmodifiableOrderError: When a stored word the request needs is outside the route's words.
            OrderNotReadyError: When Redis does not hold a value the request needs.
            InvalidOrderError: When the prices after the change do not fit the order type after the change.
        """
        order = stored_order.order
        self.changed_fields = list(modify_request.changed_fields)
        self.transaction_type = self.stored_word(
            order,
            'transaction_type',
            self.TRANSACTION_TYPES,
        )
        self.product = self.stored_word(order, 'product', self.PRODUCTS)
        self.exchange = self.stored_text(order, 'exchange')
        self.tradingsymbol = self.stored_text(order, 'tradingsymbol')
        self.instrument_token = self.stored_text(order, 'instrument_token')
        self.tag = self.stored_text(order, 'tag')

        if modify_request.changes('order_type'):
            self.order_type = modify_request.order_type
        else:
            self.order_type = self.stored_word(
                order,
                'order_type',
                self.ORDER_TYPES,
            )
        if modify_request.changes('validity'):
            self.validity = modify_request.validity
        else:
            self.validity = self.stored_word(order, 'validity', self.VALIDITIES)

        self.quantity = self.stored_quantity(order, 'quantity', True)
        self.disclosed_quantity = self.stored_quantity(
            order,
            'disclosed_quantity',
            False,
        )

        stored_order_type = self.stored_text(order, 'order_type')
        self.price = self.merged_price(
            modify_request,
            order,
            'price',
            modify_request.price,
            self.order_type in OrderRequest.PRICED_ORDER_TYPES,
            stored_order_type in OrderRequest.PRICED_ORDER_TYPES,
        )
        self.trigger_price = self.merged_price(
            modify_request,
            order,
            'trigger_price',
            modify_request.trigger_price,
            self.order_type in OrderRequest.TRIGGERED_ORDER_TYPES,
            stored_order_type in OrderRequest.TRIGGERED_ORDER_TYPES,
        )
        self.price_text = str(self.price or 0)
        self.trigger_price_text = str(self.trigger_price or 0)
        self.price_number = float(self.price or 0)
        self.trigger_price_number = float(self.trigger_price or 0)

    def stored_text(self, order, field_name):
        """Reads a stored field as text.

        Args:
            order (dict): The stored normalized order.
            field_name (str): The field's name.

        Returns:
            str | None: The value as text with surrounding spaces removed, or None when it is absent or empty.
        """
        value = order.get(field_name)
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return text

    def stored_word(self, order, field_name, words):
        """Reads a stored field that must be one of the route's words.

        Args:
            order (dict): The stored normalized order.
            field_name (str): The field's name.
            words (list): The words the route handles.

        Returns:
            str: The stored word.

        Raises:
            OrderNotReadyError: When Redis holds no value for the field.
            UnmodifiableOrderError: When the stored value is not one of the words.
        """
        word = self.stored_text(order, field_name)
        if word is None:
            message = f"Redis does not hold this order's {field_name} yet, so try again after the broker's next order book poll"
            raise OrderNotReadyError(message)
        if word not in words:
            message = f'the order has {field_name} {word}, which the modify route does not handle'
            raise UnmodifiableOrderError(message)
        return word

    def stored_quantity(self, order, field_name, required):
        """Reads a stored quantity, in the broker's own terms.

        Args:
            order (dict): The stored normalized order.
            field_name (str): `quantity` or `disclosed_quantity`.
            required (bool): Whether a missing value stops the request; when False a missing value is 0.

        Returns:
            int: The quantity.

        Raises:
            OrderNotReadyError: When a required quantity is missing or is not a whole number.
        """
        value = order.get(field_name)
        number = None
        if value is not None and value != '':
            try:
                number = decimal.Decimal(str(value).strip())
            except decimal.InvalidOperation:
                number = None
        if (
            number is not None
            and number.is_finite()
            and number == number.to_integral_value()
            and number >= 0
        ):
            return int(number)
        if not required:
            return 0
        message = f"Redis does not hold this order's {field_name} as a whole number, so try again after the broker's next order book poll"
        raise OrderNotReadyError(message)

    def merged_price(
        self,
        modify_request,
        order,
        field_name,
        given,
        needed,
        stored_needed,
    ):
        """Decides a price after the change.

        A price the caller gave is used as it is. Otherwise the stored price is carried over only when the order type after the change needs one, so a change from SL to LIMIT drops the stored trigger price, and only when the stored order type needed it too, so a change from LIMIT to SL without a trigger price is the caller's mistake rather than a gap in Redis.

        Args:
            modify_request (ModifyOrderRequest): The validated modification.
            order (dict): The stored normalized order.
            field_name (str): `price` or `trigger_price`.
            given (decimal.Decimal | None): The price the caller gave, or None.
            needed (bool): Whether the order type after the change needs this price.
            stored_needed (bool): Whether the stored order type needed this price.

        Returns:
            decimal.Decimal | None: The price, or None when the order type takes none.

        Raises:
            InvalidOrderError: When a needed price is given as zero or is not given for an order type the stored order did not have, or a price is given that the order type does not take.
            OrderNotReadyError: When a needed price is not given and Redis holds no positive stored price for an order that already needed one.
        """
        order_type = self.order_type
        if modify_request.changes(field_name):
            if needed and not given:
                message = f'a {order_type} order needs a {field_name}'
                raise InvalidOrderError(message)
            if not needed and given:
                message = f'a {order_type} order takes no {field_name}'
                raise InvalidOrderError(message)
            if not needed:
                return None
            return given
        if not needed:
            return None
        if not stored_needed:
            message = f'a {order_type} order needs a {field_name}'
            raise InvalidOrderError(message)
        stored_price = None
        value = order.get(field_name)
        if value is not None and value != '':
            try:
                stored_price = decimal.Decimal(str(value).strip())
            except decimal.InvalidOperation:
                stored_price = None
        usable = (
            stored_price is not None
            and stored_price.is_finite()
            and stored_price > 0
        )
        if not usable:
            message = f"Redis does not hold this {order_type} order's {field_name}, so give {field_name}"
            raise OrderNotReadyError(message)
        return stored_price

    def changes(self, field_name):
        """Whether the caller gave a field to change.

        Args:
            field_name (str): The field's name.

        Returns:
            bool: True when the field is changed.
        """
        return field_name in self.changed_fields

    def with_quantities(self, quantity, disclosed_quantity):
        """A copy of the modification carrying quantities in the broker's own terms.

        Args:
            quantity (int): The total quantity the broker's request carries.
            disclosed_quantity (int): The disclosed quantity the broker's request carries.

        Returns:
            OrderModification: The copy; this modification is unchanged.
        """
        broker_modification = copy.copy(self)
        broker_modification.quantity = quantity
        broker_modification.disclosed_quantity = disclosed_quantity
        return broker_modification
