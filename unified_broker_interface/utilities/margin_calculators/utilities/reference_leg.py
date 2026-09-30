"""One order every broker's margin calculator is asked about, in terms any broker can translate."""


class ReferenceLeg:
    """An order to price, described once for every broker: the instrument, the side, the product, the quantity in units and the price.

    Attributes:
        name (str): A short name for the output, such as `NIFTY future sold`.
        instrument (Instrument): The instrument, with every broker's order handle.
        transaction_type (str): `BUY` or `SELL`.
        product (str): `CNC`, `MIS` or `NRML`.
        units (int): The quantity in units, such as shares, index units or barrels.
        price (decimal.Decimal): The limit price.
    """

    def __init__(self, name, instrument, transaction_type, product, units, price):
        """Builds the leg.

        Args:
            name (str): A short name for the output.
            instrument (Instrument): The instrument.
            transaction_type (str): `BUY` or `SELL`.
            product (str): `CNC`, `MIS` or `NRML`.
            units (int): The quantity in units.
            price (decimal.Decimal): The limit price.

        Returns:
            None: This method returns nothing.
        """
        self.name = name
        self.instrument = instrument
        self.transaction_type = transaction_type
        self.product = product
        self.units = units
        self.price = price

    def handle(self, broker_name):
        """A broker's order handle for the instrument.

        Args:
            broker_name (str): The broker.

        Returns:
            dict | None: The handle, with `broker_token`, `order_symbol`, `lot_size` and `tick_size`, or None when the broker has none.
        """
        return self.instrument.handles.get(broker_name)

    def is_buy(self):
        """Whether the leg buys.

        Returns:
            bool: True for `BUY`.
        """
        return self.transaction_type == 'BUY'
