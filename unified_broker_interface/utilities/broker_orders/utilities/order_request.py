"""What the place, modify and cancel requests share: the error for an invalid request and the reading and checking of their fields."""

import decimal
import re


class InvalidOrderError(ValueError):
    """A request body or query string that is not a valid order, modification or cancel; its message is answered with HTTP 400."""


class OrderRequest:
    """The base of a validated order route request.

    Attributes:
        TRUE_SPELLINGS (list): The lower-case texts read as true.
        FALSE_SPELLINGS (list): The lower-case texts read as false.
        PRICED_ORDER_TYPES (list): The order types that need a price.
        TRIGGERED_ORDER_TYPES (list): The order types that need a trigger price.
    """

    TRUE_SPELLINGS = [
        'true',
        '1',
        'yes',
    ]

    FALSE_SPELLINGS = [
        'false',
        '0',
        'no',
        '',
    ]

    PRICED_ORDER_TYPES = [
        'LIMIT',
        'SL',
    ]

    TRIGGERED_ORDER_TYPES = [
        'SL',
        'SL-M',
    ]

    def parse_flag(self, field_name, raw_value):
        """Reads a true-or-false field that may arrive as a JSON boolean or as text.

        Args:
            field_name (str): The field's name, for the error message.
            raw_value (object): The value as received, or None when the field is absent.

        Returns:
            bool: The flag, False when the field is absent.

        Raises:
            InvalidOrderError: When the value is neither true nor false.
        """
        if raw_value is None:
            return False
        if isinstance(raw_value, bool):
            return raw_value
        spelling = str(raw_value).strip().lower()
        if spelling in self.TRUE_SPELLINGS:
            return True
        if spelling in self.FALSE_SPELLINGS:
            return False
        raise InvalidOrderError(f'{field_name} must be true or false')

    def parse_choice(self, body, field_name, default, choices):
        """Reads a field that must be one of a few upper-case words.

        Args:
            body (dict): The request body.
            field_name (str): The field's name.
            default (str | None): The value when the field is absent or empty, or None when the field is required.
            choices (list): The accepted words.

        Returns:
            str: The chosen word, upper-cased.

        Raises:
            InvalidOrderError: When the value is not one of the choices.
        """
        value = str(body.get(field_name) or default or '').strip().upper()
        if value not in choices:
            message = f'{field_name} must be one of {", ".join(choices)}'
            raise InvalidOrderError(message)
        return value

    def parse_whole_number(self, body, field_name, minimum):
        """Reads a whole-number field.

        Args:
            body (dict): The request body.
            field_name (str): The field's name.
            minimum (int): The smallest accepted value.

        Returns:
            int | None: The number, or None when the field is absent or empty.

        Raises:
            InvalidOrderError: When the value is not a whole number of at least the minimum.
        """
        raw_value = body.get(field_name)
        if raw_value is None or raw_value == '':
            return None
        try:
            value = decimal.Decimal(str(raw_value).strip())
        except decimal.InvalidOperation:
            value = None
        if (
            value is None
            or not value.is_finite()
            or value != value.to_integral_value()
            or value < minimum
        ):
            message = (
                f'{field_name} must be a whole number of at least {minimum}'
            )
            raise InvalidOrderError(message)
        return int(value)

    def parse_price(self, body, field_name):
        """Reads a price field.

        Args:
            body (dict): The request body.
            field_name (str): `price` or `trigger_price`.

        Returns:
            decimal.Decimal | None: The price, or None when the field is absent or empty.

        Raises:
            InvalidOrderError: When the value is not a finite number of at least 0.
        """
        raw_value = body.get(field_name)
        if raw_value is None or raw_value == '':
            return None
        try:
            value = decimal.Decimal(str(raw_value).strip())
        except decimal.InvalidOperation:
            value = None
        if value is None or not value.is_finite() or value < 0:
            message = f'{field_name} must be a number of at least 0'
            raise InvalidOrderError(message)
        return value

    def parse_order_id(self, body, query_arguments):
        """Reads the order id.

        Args:
            body (dict): The request body.
            query_arguments (werkzeug.datastructures.MultiDict): The query string arguments.

        Returns:
            str: The order id with surrounding spaces removed.

        Raises:
            InvalidOrderError: When the order id is missing or is not 1 to 64 letters, digits, hyphens or underscores.
        """
        order_id = body.get('order_id')
        if order_id is None:
            order_id = query_arguments.get('order_id')
        if order_id is None or order_id == '':
            raise InvalidOrderError('order_id is required')
        if isinstance(order_id, int) and not isinstance(order_id, bool):
            order_id = str(order_id)
        if isinstance(order_id, str):
            order_id = order_id.strip()
        if not isinstance(order_id, str) or not re.fullmatch(
            r'[A-Za-z0-9_-]{1,64}',
            order_id,
        ):
            message = (
                'order_id must be 1 to 64 letters, digits, hyphens or underscores'
            )
            raise InvalidOrderError(message)
        return order_id

    def parse_broker(self, body, query_arguments, broker_names):
        """Reads the optional broker name.

        Args:
            body (dict): The request body.
            query_arguments (werkzeug.datastructures.MultiDict): The query string arguments.
            broker_names (list): Every broker's name.

        Returns:
            str | None: The broker name, lower-cased, or None when not given.

        Raises:
            InvalidOrderError: When the name is not one of the brokers.
        """
        requested_broker = body.get('broker')
        if requested_broker is None:
            requested_broker = query_arguments.get('broker')
        if requested_broker is None or requested_broker == '':
            return None
        requested_broker = str(requested_broker).strip().lower()
        if requested_broker not in broker_names:
            message = 'broker must be one of ' + ', '.join(broker_names)
            raise InvalidOrderError(message)
        return requested_broker

    def handle_lot_size_problem(self, quantity, handle):
        """Checks a quantity in units against a broker's lot size.

        Args:
            quantity (int): The quantity in units.
            handle (dict): The broker's order handle.

        Returns:
            str | None: The error message when the quantity is not a whole number of lots, or None.
        """
        try:
            lot_size = decimal.Decimal(str(handle.get('lot_size')))
        except decimal.InvalidOperation:
            return None
        if not lot_size.is_finite() or lot_size <= 0:
            return None
        if decimal.Decimal(quantity) % lot_size == 0:
            return None
        lot_text = format(lot_size.normalize(), 'f')
        return f'quantity must be a whole number of lots of {lot_text}'

    def quantities_off_lot_problem(self, units_per_lot, quantities):
        """Checks quantities in units against a currency or commodity contract's trusted size.

        Args:
            units_per_lot (decimal.Decimal): Quotation units per lot, from today's contract size decision.
            quantities (dict): Each quantity field's name to its value in units, in the order they are checked; a None value is not checked.

        Returns:
            str | None: The error message for the first quantity that is not a whole number of lots, or None.
        """
        lot_text = format(units_per_lot.normalize(), 'f')
        for field_name, value in quantities.items():
            if value is None:
                continue
            if decimal.Decimal(value) % units_per_lot != 0:
                return f'{field_name} must be a whole number of lots of {lot_text}'
        return None

    def agreed_tick_size(self, handles):
        """Finds the tick size most brokers agree on for the instrument.

        Args:
            handles (dict): Every broker's order handle, by broker name.

        Returns:
            decimal.Decimal | None: The tick size with the most brokers behind it, or None when there is none or two sizes tie.
        """
        tick_size_counts = {}
        for broker_handle in handles.values():
            if not isinstance(broker_handle, dict):
                continue
            try:
                tick_size = decimal.Decimal(str(broker_handle.get('tick_size')))
            except decimal.InvalidOperation:
                continue
            if tick_size.is_finite() and tick_size > 0:
                count = tick_size_counts.get(tick_size, 0)
                tick_size_counts[tick_size] = count + 1
        agreed_tick_size = None
        highest_count = 0
        tied = False
        for tick_size, count in tick_size_counts.items():
            if count > highest_count:
                agreed_tick_size = tick_size
                highest_count = count
                tied = False
            elif count == highest_count:
                tied = True
        if tied:
            return None
        return agreed_tick_size

    def rounded_to_tick(self, price, tick_size, towards_passive=None):
        """Rounds a price to a whole number of ticks, which every price the engine computes must be.

        Nothing in this project rounded a price before. The order routes only ever checked one, refusing an order whose price was not already a whole number of ticks, because until now every price came from a caller who had chosen it. A price the engine works out itself — a midpoint, a percentage offset, a level from the depth plus a buffer — will land between ticks most of the time, and an exchange refuses it.

        A midpoint of a one-tick spread falls exactly between two ticks, so which way it goes has to be chosen rather than left to the arithmetic. `towards_passive` says whose side to round towards: `BUY` rounds down, which bids less and rests rather than crossing, and `SELL` rounds up. Left out, it rounds half away from zero, which is what a person expects of a number.

        Args:
            price (decimal.Decimal | float | int | str): The price to round.
            tick_size (decimal.Decimal): The instrument's tick size, which must be above zero.
            towards_passive (str | None): `BUY` to round down, `SELL` to round up, or None to round to the nearest.

        Returns:
            decimal.Decimal: The rounded price, a whole number of ticks.

        Raises:
            ValueError: When the tick size is not a positive number, since rounding to it would be meaningless.
        """
        if tick_size is None or tick_size <= 0:
            raise ValueError(f'tick size must be above zero, not {tick_size!r}')
        value = decimal.Decimal(str(price))
        ticks = value / tick_size
        if towards_passive == 'BUY':
            whole_ticks = ticks.to_integral_value(rounding=decimal.ROUND_FLOOR)
        elif towards_passive == 'SELL':
            whole_ticks = ticks.to_integral_value(rounding=decimal.ROUND_CEILING)
        else:
            whole_ticks = ticks.to_integral_value(
                rounding=decimal.ROUND_HALF_UP,
            )
        # Quantized to the tick's own exponent rather than normalized: normalizing turns a round
        # 1000 into Decimal('1E+3'), which reaches a broker as the string "1E+3" and is refused.
        return (whole_ticks * tick_size).quantize(tick_size)

    def prices_off_tick_problem(self, handles, prices):
        """Checks prices against the tick size most brokers agree on.

        Args:
            handles (dict): Every broker's order handle, by broker name.
            prices (dict): Each price field's name to its value, in the order they are checked; a None or zero value is not checked.

        Returns:
            str | None: The error message for the first price that is not a whole number of ticks, or None.
        """
        agreed_tick_size = self.agreed_tick_size(handles)
        if agreed_tick_size is None:
            return None
        for field_name, value in prices.items():
            if value and value % agreed_tick_size != 0:
                tick_text = format(agreed_tick_size.normalize(), 'f')
                return (
                    f'{field_name} must be a whole number of ticks of {tick_text}'
                )
        return None
