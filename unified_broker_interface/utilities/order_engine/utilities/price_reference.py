"""Working a price out from the live quote, so a caller can ask for a level rather than a number."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)

HUNDRED = decimal.Decimal('100')


class PriceReference:
    """Turns `{"kind": "offer_level", "level": 2, "buffer_percent": 0.1}` into a price.

    The sibling project's `TradeableInstrument` has thirty-three methods that place an order — buy at the best bid, sell at the third best offer, buy at the midpoint, sell at the volume weighted average price, and so on. They are not thirty-three order types. They are a side, a price reference and a quantity reference crossed with each other, and this class is the price half.

    It reads no store. The engine reads `unified:quotes:live` and hands the quote in, which keeps the round trips an order costs countable and lets every one of these be checked offline against a quote that never existed.

    Every price it returns is rounded to the instrument's tick size, towards the passive side. A midpoint of a one-tick spread falls exactly between two ticks, and rounding a buy up there would cross the spread and take liquidity when the caller asked to rest.

    Attributes:
        rounder (OrderRequest): Anything with `rounded_to_tick`, which is where the rounding lives.
    """

    def __init__(self, rounder):
        """Builds the resolver.

        Args:
            rounder (OrderRequest): The validated order, or anything else carrying `rounded_to_tick`.

        Returns:
            None: This method returns nothing.
        """
        self.rounder = rounder

    def resolve(self, reference, quote, transaction_type, tick_size):
        """The price a reference names, rounded to the tick.

        Args:
            reference (dict): The parsed `price_reference`.
            quote (dict | None): The instrument's entry in `unified:quotes:live`.
            transaction_type (str): `BUY` or `SELL`, which decides which side of the book is which.
            tick_size (decimal.Decimal): The instrument's tick size.

        Returns:
            decimal.Decimal: The price to send.

        Raises:
            RefusedRequestError: With HTTP 503 when the quote does not carry what the reference needs, and 400 when the price works out at zero or below.
        """
        kind = reference['kind']
        if kind == 'absolute':
            price = decimal.Decimal(str(reference['price']))
        else:
            price = self.from_quote(kind, reference, quote, transaction_type)
        price = self.with_offsets(
            price,
            reference,
            transaction_type,
            tick_size,
        )
        rounded = self.rounder.rounded_to_tick(
            price,
            tick_size,
            self.passive_side(kind, transaction_type),
        )
        if rounded <= 0:
            raise RefusedRequestError.refusal(
                f'the {kind} price reference worked out at {rounded}, which is '
                'not a price an order can carry',
                400,
            )
        return rounded

    def passive_side(self, kind, transaction_type):
        """Which way to round, so a resting order rests and a crossing one crosses.

        A `marketable` reference is meant to take liquidity, so rounding it towards the passive side would work against what it is for; it rounds towards the market instead.

        Args:
            kind (str): The reference's kind.
            transaction_type (str): `BUY` or `SELL`.

        Returns:
            str: `BUY` or `SELL`, as `rounded_to_tick` takes it.
        """
        if kind == 'marketable':
            return 'SELL' if transaction_type == 'BUY' else 'BUY'
        return transaction_type

    def from_quote(self, kind, reference, quote, transaction_type):
        """The price a reference names, before offsets and rounding.

        Args:
            kind (str): The reference's kind.
            reference (dict): The parsed reference.
            quote (dict | None): The instrument's quote.
            transaction_type (str): `BUY` or `SELL`.

        Returns:
            decimal.Decimal: The price.

        Raises:
            RefusedRequestError: With HTTP 503 when the quote does not carry what is needed.
        """
        if not isinstance(quote, dict):
            raise RefusedRequestError.refusal(
                f'a {kind} price reference needs a live quote for this '
                'instrument and there is none',
                503,
            )
        if kind == 'last':
            return self.number(quote.get('last_price'), 'last_price', kind)
        if kind == 'vwap':
            # The unified quote calls it average_price; there is no field named vwap.
            return self.number(
                quote.get('average_price'),
                'average_price',
                kind,
            )
        if kind == 'mid':
            bid = self.level_price(quote, 'buy', 1, kind)
            offer = self.level_price(quote, 'sell', 1, kind)
            return (bid + offer) / 2
        if kind == 'bid_level':
            return self.level_price(quote, 'buy', reference['level'], kind)
        if kind == 'offer_level':
            return self.level_price(quote, 'sell', reference['level'], kind)
        # marketable: the touch on the other side, which is what an order has to reach to fill now.
        side = 'sell' if transaction_type == 'BUY' else 'buy'
        return self.level_price(quote, side, 1, kind)

    def level_price(self, quote, side, level, kind):
        """One level of one side of the depth.

        Args:
            quote (dict): The instrument's quote.
            side (str): `buy` or `sell`, as the depth names them.
            level (int): The level, counting the touch as 1.
            kind (str): The reference's kind, for the message.

        Returns:
            decimal.Decimal: The price at that level.

        Raises:
            RefusedRequestError: With HTTP 503 when the depth does not reach that level.
        """
        depth = quote.get('depth')
        levels = (depth or {}).get(side) if isinstance(depth, dict) else None
        if not isinstance(levels, list) or len(levels) < level:
            raise RefusedRequestError.refusal(
                f'a {kind} price reference needs {level} level(s) on the '
                f'{side} side of the book and the quote carries '
                f'{len(levels) if isinstance(levels, list) else 0}',
                503,
            )
        entry = levels[level - 1]
        if not isinstance(entry, dict):
            raise RefusedRequestError.refusal(
                f'the {side} side of the book is not readable for a {kind} '
                'price reference',
                503,
            )
        return self.number(entry.get('price'), f'{side} level {level}', kind)

    def number(self, value, field_name, kind):
        """One quote field as a number above zero.

        Args:
            value (object): The field's value.
            field_name (str): Its name, for the message.
            kind (str): The reference's kind, for the message.

        Returns:
            decimal.Decimal: The value.

        Raises:
            RefusedRequestError: With HTTP 503 when the field is missing, unreadable or not above zero.
        """
        try:
            number = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError):
            number = None
        if number is None or not number.is_finite() or number <= 0:
            raise RefusedRequestError.refusal(
                f'a {kind} price reference needs {field_name} in the quote and '
                f'it is {value!r}',
                503,
            )
        return number

    def with_offsets(self, price, reference, transaction_type, tick_size):
        """The price moved by whatever offsets the reference carries.

        An offset is always applied in the direction that makes the order more likely to fill, because that is what a caller asking for "the offer plus a tenth of a per cent" means: pay a little more to get done. A negative offset therefore improves the price instead.

        Args:
            price (decimal.Decimal): The price from the quote.
            reference (dict): The parsed reference.
            transaction_type (str): `BUY` or `SELL`.
            tick_size (decimal.Decimal): The instrument's tick size.

        Returns:
            decimal.Decimal: The moved price.
        """
        direction = decimal.Decimal(1 if transaction_type == 'BUY' else -1)
        for name in ('buffer_percent', 'offset_percent'):
            percent = reference.get(name)
            if percent is not None:
                price = price + (price * percent / HUNDRED) * direction
        ticks = reference.get('offset_ticks')
        if ticks is not None:
            price = price + tick_size * decimal.Decimal(ticks) * direction
        return price
