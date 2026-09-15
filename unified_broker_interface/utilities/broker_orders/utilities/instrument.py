"""The instrument an order is for, as today's mapping describes it."""

from unified_broker_interface.utilities.broker_orders.utilities.tradeable_segments import (
    TradeableSegments,
)


class Instrument:
    """One mapped instrument: its identity, every broker's order handle, and the market a broker's table is keyed by.

    Attributes:
        instrument_id (str): The instrument id.
        identity (dict): The identity from the mapping: exchange, segment, shape and identity fields.
        handles (dict): Broker names to order handles, each with `broker_token`, `order_symbol`, `lot_size` and `tick_size`.
        segment (str): The exchange-prefixed segment, such as `nse_equities`, or an empty string when the identity has none.
        exchange (str): The exchange part of the segment, such as `nse`.
        bare_segment (str): The segment without its exchange, such as `equities`.
    """

    def __init__(self, instrument_id, identity, handles):
        """Builds the instrument from its decoded identity and handles.

        Args:
            instrument_id (str): The instrument id.
            identity (dict): The decoded identity.
            handles (dict): The decoded order handles, by broker name.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = instrument_id
        self.identity = identity
        self.handles = handles
        self.segment = str(identity.get('segment') or '')
        exchange, _, bare_segment = self.segment.partition('_')
        self.exchange = exchange
        self.bare_segment = bare_segment

    def is_tradeable(self):
        """Whether orders are sent for this instrument's exchange and segment.

        Returns:
            bool: True when both are tradeable.
        """
        if self.exchange not in TradeableSegments.EXCHANGES:
            return False
        return self.bare_segment in TradeableSegments.SHAPES

    def kind(self):
        """Whether the instrument is traded for cash or as a derivative; only meaningful when it is tradeable.

        Returns:
            str: `cash` for a security, `derivative` for a future or option.
        """
        if TradeableSegments.SHAPES[self.bare_segment] == 'security':
            return 'cash'
        return 'derivative'

    def market(self):
        """The key a broker's market table is looked up by; only meaningful when the instrument is tradeable.

        Returns:
            tuple: `(exchange, asset class, kind)`, such as `('nse', 'securities', 'cash')`.
        """
        asset_class = TradeableSegments.ASSET_CLASSES[self.bare_segment]
        return (self.exchange, asset_class, self.kind())
