"""The parameters of `PUT /api/orders/modify`, validated."""

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    OrderRequest,
)


class ModifyOrderRequest(OrderRequest):
    """One modification as the caller asked for it: which order, and the fields to change.

    `order_id`, `broker` and `dry_run` are read from the JSON body first and the query string second, as a cancel reads them. The fields to change are read from the body only. A field that is absent or empty keeps the stored order's value.

    Attributes:
        MODIFIABLE_FIELD_NAMES (list): The fields a modification can change, in the order they are listed.
        order_id (str): The broker's order id.
        broker (str | None): The broker the caller named, lower-cased, or None.
        dry_run (bool): Whether to answer with the request instead of sending it.
        quantity (int | None): The new total quantity in units, or None when it is not changed.
        disclosed_quantity (int | None): The new disclosed quantity in units, or None when it is not changed.
        price (decimal.Decimal | None): The new limit price, or None when it is not changed.
        trigger_price (decimal.Decimal | None): The new trigger price, or None when it is not changed.
        order_type (str | None): The new order type, or None when it is not changed.
        validity (str | None): The new validity, or None when it is not changed.
        changed_fields (list): The names of the fields the caller gave, in `MODIFIABLE_FIELD_NAMES` order.
    """

    MODIFIABLE_FIELD_NAMES = [
        'quantity',
        'disclosed_quantity',
        'price',
        'trigger_price',
        'order_type',
        'validity',
    ]

    def __init__(self, body, query_arguments, broker_names):
        """Validates the modification's parameters.

        Args:
            body (object): The decoded JSON body, or None when there is none or it is not JSON.
            query_arguments (werkzeug.datastructures.MultiDict): The query string arguments.
            broker_names (list): Every broker's name, for checking `broker`.

        Returns:
            None: This method returns nothing.

        Raises:
            InvalidOrderError: When the body is not an object, a parameter is invalid, or the body changes no field.
        """
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise InvalidOrderError('the request body must be a JSON object')
        self.order_id = self.parse_order_id(body, query_arguments)
        self.broker = self.parse_broker(body, query_arguments, broker_names)
        raw_dry_run = body.get('dry_run')
        if raw_dry_run is None:
            raw_dry_run = query_arguments.get('dry_run')
        self.dry_run = self.parse_flag('dry_run', raw_dry_run)

        self.quantity = self.parse_whole_number(body, 'quantity', 1)
        self.disclosed_quantity = self.parse_whole_number(
            body,
            'disclosed_quantity',
            0,
        )
        if self.quantity is not None and self.disclosed_quantity is not None:
            if self.disclosed_quantity > self.quantity:
                message = 'disclosed_quantity cannot be more than quantity'
                raise InvalidOrderError(message)
        self.price = self.parse_price(body, 'price')
        self.trigger_price = self.parse_price(body, 'trigger_price')
        self.order_type = self.parse_optional_choice(
            body,
            'order_type',
            [
                'MARKET',
                'LIMIT',
                'SL',
                'SL-M',
            ],
        )
        self.validity = self.parse_optional_choice(
            body,
            'validity',
            [
                'DAY',
                'IOC',
            ],
        )

        given_values = {
            'quantity': self.quantity,
            'disclosed_quantity': self.disclosed_quantity,
            'price': self.price,
            'trigger_price': self.trigger_price,
            'order_type': self.order_type,
            'validity': self.validity,
        }
        self.changed_fields = []
        for field_name in self.MODIFIABLE_FIELD_NAMES:
            if given_values[field_name] is not None:
                self.changed_fields.append(field_name)
        if not self.changed_fields:
            message = (
                'give at least one of quantity, disclosed_quantity, price, trigger_price, order_type or validity to change'
            )
            raise InvalidOrderError(message)

    def parse_optional_choice(self, body, field_name, choices):
        """Reads a field that, when given, must be one of a few upper-case words.

        Args:
            body (dict): The request body.
            field_name (str): The field's name.
            choices (list): The accepted words.

        Returns:
            str | None: The chosen word, upper-cased, or None when the field is absent or empty.

        Raises:
            InvalidOrderError: When the value is given and is not one of the choices.
        """
        raw_value = body.get(field_name)
        if raw_value is None or raw_value == '':
            return None
        return self.parse_choice(body, field_name, None, choices)

    def changes(self, field_name):
        """Whether the caller gave a field to change.

        Args:
            field_name (str): One of `MODIFIABLE_FIELD_NAMES`.

        Returns:
            bool: True when the field is changed.
        """
        return field_name in self.changed_fields
