"""The body of `POST /api/orders/place`, validated into one order."""

import copy
import datetime
import decimal
import re
import uuid

from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    InvalidOrderError,
)
from unified_broker_interface.utilities.broker_orders.utilities.order_request import (
    OrderRequest,
)
from unified_broker_interface.utilities.broker_orders.utilities.tradeable_segments import (
    TradeableSegments,
)


class PlaceOrderRequest(OrderRequest):
    """One order as the caller asked for it, with every field checked and in the shared vocabulary.

    Building one reads nothing but the body, so every check here costs no I/O.

    Attributes:
        transaction_type (str): `BUY` or `SELL`.
        product (str): `CNC`, `MIS` or `NRML`.
        order_type (str): `MARKET`, `LIMIT`, `SL` or `SL-M`.
        validity (str): `DAY` or `IOC`.
        quantity (int): The quantity in units, at least 1.
        disclosed_quantity (int): The disclosed quantity, 0 when not given.
        price (decimal.Decimal | None): The limit price, or None.
        trigger_price (decimal.Decimal | None): The trigger price, or None.
        price_text (str): The price as text, `0` when there is none.
        trigger_price_text (str): The trigger price as text, `0` when there is none.
        price_number (float): The price as a float, 0.0 when there is none.
        trigger_price_number (float): The trigger price as a float, 0.0 when there is none.
        after_market (bool): Whether this is an after-market order.
        dry_run (bool): Whether to answer with the request instead of sending it.
        tag (str | None): The caller's tag, 1 to 20 letters and digits, or None.
        instrument_id (str | None): The instrument id when the body gave one, in canonical form.
        catalogue_segment (str | None): The exchange-prefixed segment to search when the body gave identity fields instead.
        catalogue_prefix (str | None): The catalogue member prefix the identity fields make.
    """

    def __init__(self, body):
        """Validates a request body into an order.

        Args:
            body (object): The decoded JSON body, or None when the body was not JSON.

        Returns:
            None: This method returns nothing.

        Raises:
            InvalidOrderError: When any field is missing, malformed or inconsistent with another.
        """
        if not isinstance(body, dict):
            raise InvalidOrderError('the request body must be a JSON object')
        self.transaction_type = self.parse_choice(
            body,
            'transaction_type',
            None,
            [
                'BUY',
                'SELL',
            ],
        )
        self.product = self.parse_choice(
            body,
            'product',
            None,
            [
                'CNC',
                'MIS',
                'NRML',
            ],
        )
        self.order_type = self.parse_choice(
            body,
            'order_type',
            None,
            [
                'MARKET',
                'LIMIT',
                'SL',
                'SL-M',
            ],
        )
        self.validity = self.parse_choice(
            body,
            'validity',
            'DAY',
            [
                'DAY',
                'IOC',
            ],
        )
        self.parse_quantities(body)
        self.price = self.parse_price(body, 'price')
        self.trigger_price = self.parse_price(body, 'trigger_price')
        self.check_prices_fit_the_order_type()
        self.price_text = str(self.price or 0)
        self.trigger_price_text = str(self.trigger_price or 0)
        self.price_number = float(self.price or 0)
        self.trigger_price_number = float(self.trigger_price or 0)
        self.after_market = self.parse_flag(
            'after_market',
            body.get('after_market'),
        )
        self.dry_run = self.parse_flag('dry_run', body.get('dry_run'))
        self.tag = self.parse_tag(body.get('tag'))
        self.instrument_id = None
        self.catalogue_segment = None
        self.catalogue_prefix = None
        self.parse_instrument(body)

    def parse_quantities(self, body):
        """Reads `quantity` and `disclosed_quantity` and checks them against each other.

        Args:
            body (dict): The request body.

        Returns:
            None: This method returns nothing.

        Raises:
            InvalidOrderError: When the quantity is missing or either value is invalid.
        """
        quantity = self.parse_whole_number(body, 'quantity', 1)
        if quantity is None:
            raise InvalidOrderError('quantity is required')
        disclosed_quantity = self.parse_whole_number(
            body,
            'disclosed_quantity',
            0,
        )
        if disclosed_quantity is None:
            disclosed_quantity = 0
        if disclosed_quantity > quantity:
            message = 'disclosed_quantity cannot be more than quantity'
            raise InvalidOrderError(message)
        self.quantity = quantity
        self.disclosed_quantity = disclosed_quantity

    def check_prices_fit_the_order_type(self):
        """Checks that a price and a trigger price are given exactly when the order type needs them.

        Returns:
            None: This method returns nothing.

        Raises:
            InvalidOrderError: When a needed price is missing or an unneeded one is given.
        """
        order_type = self.order_type
        priced = order_type in self.PRICED_ORDER_TYPES
        triggered = order_type in self.TRIGGERED_ORDER_TYPES
        if priced and not self.price:
            raise InvalidOrderError(f'a {order_type} order needs a price')
        if not priced and self.price:
            raise InvalidOrderError(f'a {order_type} order takes no price')
        if triggered and not self.trigger_price:
            message = f'a {order_type} order needs a trigger_price'
            raise InvalidOrderError(message)
        if not triggered and self.trigger_price:
            message = f'a {order_type} order takes no trigger_price'
            raise InvalidOrderError(message)

    def parse_tag(self, raw_tag):
        """Reads the optional tag.

        Args:
            raw_tag (object): The `tag` field as received.

        Returns:
            str | None: The tag with surrounding spaces removed, or None when absent or empty.

        Raises:
            InvalidOrderError: When the tag is not 1 to 20 letters and digits.
        """
        if raw_tag is None or raw_tag == '':
            return None
        message = 'tag must be 1 to 20 letters and digits'
        if not isinstance(raw_tag, str):
            raise InvalidOrderError(message)
        tag = raw_tag.strip()
        if not re.fullmatch(r'[A-Za-z0-9]{1,20}', tag):
            raise InvalidOrderError(message)
        return tag

    def parse_instrument(self, body):
        """Reads the instrument, as an instrument id or as an exchange, a segment and the segment's identity fields.

        Args:
            body (dict): The request body.

        Returns:
            None: This method returns nothing.

        Raises:
            InvalidOrderError: When the instrument is not named in a valid way.
        """
        raw_instrument_id = body.get('instrument_id')
        if raw_instrument_id:
            try:
                self.instrument_id = str(
                    uuid.UUID(str(raw_instrument_id).strip()),
                )
            except ValueError:
                raise InvalidOrderError('instrument_id must be a UUID')
            return

        exchange = str(body.get('exchange') or '').strip().lower()
        if exchange not in TradeableSegments.EXCHANGES:
            exchange_names = ', '.join(TradeableSegments.EXCHANGES[:-1])
            last_exchange_name = TradeableSegments.EXCHANGES[-1]
            message = (
                f'give instrument_id, or an exchange of {exchange_names} or {last_exchange_name} with a segment and its identity fields'
            )
            raise InvalidOrderError(message)
        bare_segment = str(body.get('segment') or '').strip().lower()
        if bare_segment.startswith(exchange + '_'):
            bare_segment = bare_segment[len(exchange) + 1:]
        if bare_segment not in TradeableSegments.SHAPES:
            message = (
                f'orders are not sent for the segment {body.get("segment")!r}'
            )
            raise InvalidOrderError(message)
        shape = TradeableSegments.SHAPES[bare_segment]
        self.catalogue_segment = f'{exchange}_{bare_segment}'

        if shape == 'security':
            self.catalogue_prefix = self.security_prefix(body)
        else:
            self.catalogue_prefix = self.expiring_prefix(body, shape)
        if shape == 'option':
            self.catalogue_prefix = (
                self.catalogue_prefix + self.option_suffix(body)
            )

    def security_prefix(self, body):
        """Builds the catalogue prefix of a security from its symbol.

        Args:
            body (dict): The request body.

        Returns:
            str: The prefix, such as `RELIANCE|`.

        Raises:
            InvalidOrderError: When there is no symbol.
        """
        symbol = str(body.get('symbol') or '').strip().upper()
        if not symbol:
            raise InvalidOrderError('a security segment needs symbol')
        return symbol.replace('|', '/') + '|'

    def expiring_prefix(self, body, shape):
        """Builds the catalogue prefix of a future or option from its underlying and expiry.

        Args:
            body (dict): The request body.
            shape (str): `future` or `option`.

        Returns:
            str: The prefix, such as `NIFTY|2026-09-29|`.

        Raises:
            InvalidOrderError: When the underlying or expiry is missing, or the expiry is not an ISO date.
        """
        underlying_symbol = str(body.get('underlying_symbol') or '')
        underlying_symbol = underlying_symbol.strip().upper()
        expiry_text = str(body.get('expiry_date') or '').strip()
        if not underlying_symbol or not expiry_text:
            message = (
                f'a {shape} segment needs underlying_symbol and expiry_date'
            )
            raise InvalidOrderError(message)
        try:
            expiry_date = datetime.date.fromisoformat(expiry_text)
        except ValueError:
            message = 'expiry_date must be a date in YYYY-MM-DD format'
            raise InvalidOrderError(message)
        return (
            underlying_symbol.replace('|', '/')
            + '|'
            + expiry_date.isoformat()
            + '|'
        )

    def option_suffix(self, body):
        """Builds the part of an option's catalogue prefix that follows the expiry.

        Args:
            body (dict): The request body.

        Returns:
            str: The strike, padded as the catalogue stores it, and the option type, such as `00000025000.0000|CE|`.

        Raises:
            InvalidOrderError: When the strike is not a number or the option type is not CE or PE.
        """
        strike_text = str(body.get('strike_price') or '').strip()
        option_type = str(body.get('option_type') or '').strip().upper()
        try:
            strike_price = decimal.Decimal(strike_text)
        except decimal.InvalidOperation:
            strike_price = None
        if strike_price is None or not strike_price.is_finite():
            message = 'an option segment needs a numeric strike_price'
            raise InvalidOrderError(message)
        if option_type not in (
            'CE',
            'PE',
        ):
            raise InvalidOrderError('option_type must be CE or PE')
        return f'{strike_price:016.4f}' + '|' + option_type + '|'

    def lot_size_problem(self, handle):
        """Checks the quantity against the chosen broker's lot size.

        Args:
            handle (dict): The chosen broker's order handle.

        Returns:
            str | None: The error message when the quantity is not a whole number of lots, or None.
        """
        return self.handle_lot_size_problem(self.quantity, handle)

    def contract_lot_problem(self, units_per_lot):
        """Checks the quantity and disclosed quantity against a currency or commodity contract's trusted size.

        Args:
            units_per_lot (decimal.Decimal): Quotation units per lot, from today's contract size decision.

        Returns:
            str | None: The error message for the first quantity that is not a whole number of lots, or None.
        """
        quantities = {
            'quantity': self.quantity,
            'disclosed_quantity': self.disclosed_quantity,
        }
        return self.quantities_off_lot_problem(units_per_lot, quantities)

    def with_quantities(self, quantity, disclosed_quantity):
        """A copy of the order carrying quantities in a broker's own terms, for building that broker's request.

        Args:
            quantity (int): The quantity the broker's request carries.
            disclosed_quantity (int): The disclosed quantity the broker's request carries.

        Returns:
            PlaceOrderRequest: The copy; this order is unchanged.
        """
        broker_order = copy.copy(self)
        broker_order.quantity = quantity
        broker_order.disclosed_quantity = disclosed_quantity
        return broker_order

    def tick_size_problem(self, handles):
        """Checks the price and trigger price against the tick size most brokers agree on.

        Args:
            handles (dict): Every broker's order handle, by broker name.

        Returns:
            str | None: The error message for the first price that is not a whole number of ticks, or None.
        """
        prices = {
            'price': self.price,
            'trigger_price': self.trigger_price,
        }
        return self.prices_off_tick_problem(handles, prices)
