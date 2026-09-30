"""One order together with what Redis holds about its instrument, ready to have its margin estimated."""

import decimal


class PricedLeg:
    """One order leg with its instrument's identity, its last traded price and its underlying's last traded price.

    Attributes:
        instrument_id (str): The instrument's id.
        order (PlaceOrderRequest): The order.
        identity (dict): The instrument's identity from the catalogue: `segment`, `shape`, `underlying_symbol`, `expiry_date`, `strike_price` and `option_type`.
        last_price (decimal.Decimal | None): The instrument's last traded price, or None when no quote is held.
        underlying_price (decimal.Decimal | None): The underlying's last traded price, or None when the instrument has no underlying or no quote is held for it.
    """

    def __init__(self, instrument_id, order, identity, last_price, underlying_price):
        """Builds the leg.

        Args:
            instrument_id (str): The instrument's id.
            order (PlaceOrderRequest): The order.
            identity (dict): The instrument's identity.
            last_price (decimal.Decimal | None): The last traded price.
            underlying_price (decimal.Decimal | None): The underlying's last traded price.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = instrument_id
        self.order = order
        self.identity = identity
        self.last_price = last_price
        self.underlying_price = underlying_price

    def segment(self):
        """The catalogue segment, such as `nse_equity_index_options`.

        Returns:
            str: The segment, or an empty string when the identity has none.
        """
        return str(self.identity.get('segment') or '')

    def shape(self):
        """What kind of contract the instrument is.

        Returns:
            str: `security`, `future` or `option`, or an empty string when the identity has none.
        """
        return str(self.identity.get('shape') or '')

    def underlying_symbol(self):
        """The underlying's symbol, such as `NIFTY`, for a derivative.

        Returns:
            str | None: The symbol, or None for an instrument without one.
        """
        return self.identity.get('underlying_symbol')

    def expiry_date(self):
        """The derivative's expiry date.

        Returns:
            str | None: The date as `YYYY-MM-DD`, or None.
        """
        return self.identity.get('expiry_date')

    def strike_price(self):
        """The option's strike price.

        Returns:
            decimal.Decimal | None: The strike, or None when the instrument is not an option or the strike cannot be read.
        """
        return self.decimal_or_none(self.identity.get('strike_price'))

    def option_type(self):
        """Whether the option is a call or a put.

        Returns:
            str | None: `CE` or `PE`, or None when the instrument is not an option.
        """
        return self.identity.get('option_type')

    def is_option(self):
        """Whether the instrument is an option.

        Returns:
            bool: True for an option.
        """
        return self.shape() == 'option'

    def is_future(self):
        """Whether the instrument is a future.

        Returns:
            bool: True for a future.
        """
        return self.shape() == 'future'

    def is_buy(self):
        """Whether the order buys.

        Returns:
            bool: True for `BUY`.
        """
        return self.order.transaction_type == 'BUY'

    def direction(self):
        """The order's side as a sign.

        Returns:
            int: 1 for a buy and -1 for a sell.
        """
        if self.is_buy():
            return 1
        return -1

    def units(self):
        """The order's quantity in units, such as shares, index units or barrels.

        Returns:
            decimal.Decimal: The quantity.
        """
        return decimal.Decimal(self.order.quantity)

    def trade_price(self):
        """The price the order is expected to trade at: its limit price, else its trigger price, else the last traded price.

        Returns:
            decimal.Decimal | None: The price, or None when the order has none and no quote is held.
        """
        if self.order.price is not None:
            return decimal.Decimal(self.order.price)
        if self.order.trigger_price is not None:
            return decimal.Decimal(self.order.trigger_price)
        return self.last_price

    def market_category(self):
        """Which market the instrument trades in, for choosing a broker's margin multiplier and money pool.

        Returns:
            str: `commodity`, `currency`, `derivatives` or `equity`.
        """
        segment = self.segment()
        if 'commodit' in segment:
            return 'commodity'
        if 'currenc' in segment:
            return 'currency'
        if self.is_option() or self.is_future():
            return 'derivatives'
        return 'equity'

    @staticmethod
    def decimal_or_none(value):
        """A value as a decimal, or None when it is missing or not a finite number.

        Args:
            value (object): The value, often a string.

        Returns:
            decimal.Decimal | None: The number, or None.
        """
        if value is None or value == '':
            return None
        try:
            number = decimal.Decimal(str(value))
        except decimal.InvalidOperation:
            return None
        if not number.is_finite():
            return None
        return number
