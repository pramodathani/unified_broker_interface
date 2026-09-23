"""The instrument an order is for, as today's mapping describes it."""

import decimal
import json

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
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
        contract_size (dict | None): Today's contract size decision for a currency or commodity derivative, with `units_per_lot`, `status` and `tradeable`, or None when there is none.
    """

    def __init__(self, instrument_id, identity, handles, contract_size=None):
        """Builds the instrument from its decoded identity, handles and contract size decision.

        Args:
            instrument_id (str): The instrument id.
            identity (dict): The decoded identity.
            handles (dict): The decoded order handles, by broker name.
            contract_size (dict | None): The decoded contract size decision, or None when Redis holds none.

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
        self.contract_size = contract_size

    @classmethod
    def decoded(cls, instrument_id, identity_text, handles_text, contract_size_text):
        """Builds the instrument from its identity, order handles and contract size decision as Redis holds them.

        A contract size decision that is missing or not a JSON object is decoded as None, which leaves a currency or commodity derivative untradeable rather than refusing an order on any other instrument.

        Args:
            instrument_id (str): The instrument id.
            identity_text (str | None): The identity as Redis holds it.
            handles_text (str | None): The order handles as Redis holds them.
            contract_size_text (str | None): The contract size decision as Redis holds it.

        Returns:
            Instrument: The instrument, which may not be tradeable.

        Raises:
            RefusedRequestError: With HTTP 404 when the identity or the handles are missing or not a JSON object.
        """
        identity = None
        handles = None
        try:
            if identity_text:
                identity = json.loads(identity_text)
            if handles_text:
                handles = json.loads(handles_text)
        except ValueError:
            identity = None
            handles = None
        if not isinstance(identity, dict) or not isinstance(handles, dict):
            raise RefusedRequestError.refusal('the instrument is not mapped', 404)
        contract_size = None
        if contract_size_text:
            try:
                contract_size = json.loads(contract_size_text)
            except ValueError:
                contract_size = None
        if not isinstance(contract_size, dict):
            contract_size = None
        return cls(instrument_id, identity, handles, contract_size)

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

    def is_securities_market(self):
        """Whether the instrument trades in the securities markets, whose lot size the brokers agree on, rather than in currencies or commodities; only meaningful when it is tradeable.

        Returns:
            bool: True for equities, fixed income, funds and trusts and their derivatives.
        """
        return TradeableSegments.ASSET_CLASSES[self.bare_segment] == 'securities'

    def trusted_units_per_lot(self):
        """Today's trusted contract size, when the morning decision made one.

        Returns:
            decimal.Decimal | None: Quotation units per lot, or None when there is no decision, it is not tradeable, or its size is not a positive number.
        """
        if not isinstance(self.contract_size, dict):
            return None
        if self.contract_size.get('tradeable') is not True:
            return None
        try:
            units_per_lot = decimal.Decimal(str(self.contract_size.get('units_per_lot')))
        except decimal.InvalidOperation:
            return None
        if not units_per_lot.is_finite() or units_per_lot <= 0:
            return None
        return units_per_lot

    def contract_size_status(self):
        """The status of today's contract size decision, for a refusal's message.

        Returns:
            str: The decision's status, or `undecided` when Redis holds no decision.
        """
        if not isinstance(self.contract_size, dict):
            return 'undecided'
        return str(self.contract_size.get('status') or 'undecided')

    def market(self):
        """The key a broker's market table is looked up by; only meaningful when the instrument is tradeable.

        Returns:
            tuple: `(exchange, asset class, kind)`, such as `('nse', 'securities', 'cash')`.
        """
        asset_class = TradeableSegments.ASSET_CLASSES[self.bare_segment]
        return (self.exchange, asset_class, self.kind())
