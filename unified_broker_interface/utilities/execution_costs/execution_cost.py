"""What one filled leg cost against the mid-price when the decision to trade was made, split into its parts."""

import decimal

BASIS_POINTS = decimal.Decimal(10000)
PRICE_PLACES = decimal.Decimal('0.0001')
BASIS_POINT_PLACES = decimal.Decimal('0.01')
RUPEE_PLACES = decimal.Decimal('0.01')


class ExecutionCost:
    """One filled leg's implementation shortfall, per unit, in basis points and in rupees.

    Every part is a cost, so a positive number is money lost and a negative one is money gained. The four parts add up to the total whenever all three quotes are known:

    - `delay`: how far the mid-price moved between the decision and the engine sending the leg.
    - `latency`: how far it moved between sending and the broker's answer, which is the part that depends on the broker.
    - `half_spread`: half the spread when the broker answered, which an order that crosses the spread pays.
    - `beyond_touch`: how far the fill was beyond the best price on its side when the broker answered. It is positive when an order walked the book, which is market impact, and negative when a resting order filled inside the spread.

    A part whose quotes are missing is None, and so is the total when the decision's quote is missing.

    Attributes:
        leg (LegExecution): The filled leg.
        at_decision (QuoteMoment | None): The quote when the decision was made.
        at_send (QuoteMoment | None): The quote when the leg was sent.
        at_answer (QuoteMoment | None): The quote when the broker answered.
        segment (str | None): The instrument's segment, such as `nse_equity_options`.
        securities_market (bool): Whether the instrument trades in the securities markets, where the filled quantity is in units and so a rupee total can be worked out.
    """

    def __init__(self, leg, at_decision, at_send, at_answer, segment, securities_market):
        """Builds the cost of one leg.

        Args:
            leg (LegExecution): The filled leg.
            at_decision (QuoteMoment | None): The quote when the decision was made.
            at_send (QuoteMoment | None): The quote when the leg was sent.
            at_answer (QuoteMoment | None): The quote when the broker answered.
            segment (str | None): The instrument's segment.
            securities_market (bool): Whether the filled quantity is in units.

        Returns:
            None: This method returns nothing.
        """
        self.leg = leg
        self.at_decision = at_decision
        self.at_send = at_send
        self.at_answer = at_answer
        self.segment = segment
        self.securities_market = securities_market

    def delay(self):
        """The cost of the mid-price moving between the decision and sending.

        Returns:
            decimal.Decimal | None: Per unit, or None without both quotes.
        """
        if self.at_decision is None or self.at_send is None:
            return None
        return self.leg.side() * (self.at_send.mid() - self.at_decision.mid())

    def latency(self):
        """The cost of the mid-price moving between sending and the broker's answer.

        Returns:
            decimal.Decimal | None: Per unit, or None without both quotes.
        """
        if self.at_send is None or self.at_answer is None:
            return None
        return self.leg.side() * (self.at_answer.mid() - self.at_send.mid())

    def half_spread(self):
        """Half the spread when the broker answered.

        Returns:
            decimal.Decimal | None: Per unit, or None without the quote.
        """
        if self.at_answer is None:
            return None
        return self.at_answer.half_spread()

    def beyond_touch(self):
        """How far the fill was beyond the best price on its side when the broker answered.

        Returns:
            decimal.Decimal | None: Per unit, or None without the quote.
        """
        if self.at_answer is None:
            return None
        against_mid = self.leg.side() * (self.leg.average_price - self.at_answer.mid())
        return against_mid - self.at_answer.half_spread()

    def total(self):
        """The whole cost: the fill against the mid-price when the decision was made.

        Returns:
            decimal.Decimal | None: Per unit, or None without the decision's quote.
        """
        if self.at_decision is None:
            return None
        return self.leg.side() * (self.leg.average_price - self.at_decision.mid())

    def basis_points(self, per_unit):
        """A per-unit cost as a share of the mid-price when the decision was made.

        Args:
            per_unit (decimal.Decimal | None): A cost per unit.

        Returns:
            decimal.Decimal | None: Basis points, rounded to a hundredth, or None without the cost or the decision's quote.
        """
        if per_unit is None or self.at_decision is None:
            return None
        mid = self.at_decision.mid()
        if mid <= 0:
            return None
        return self.without_sign_on_zero((per_unit / mid * BASIS_POINTS).quantize(BASIS_POINT_PLACES))

    def total_rupees(self):
        """The whole cost of the filled quantity, for an instrument whose filled quantity is in units.

        A currency or commodity fill is reported in lots at some brokers, so its rupee total is left out rather than guessed.

        Returns:
            decimal.Decimal | None: Rupees, rounded to the paisa, or None.
        """
        total = self.total()
        if total is None or not self.securities_market:
            return None
        return (total * self.leg.filled_quantity).quantize(RUPEE_PLACES)

    def row(self):
        """The row written to `unified.order_execution_costs`.

        Returns:
            dict: Every column by name, with prices rounded to four places.
        """
        leg = self.leg
        return {
            'time': leg.sent_at,
            'parent_order_id': leg.parent_order_id,
            'leg_id': leg.leg_id,
            'synthetic_type': leg.synthetic_type,
            'leg_role': leg.leg_role,
            'broker': leg.broker,
            'instrument_id': leg.instrument_id,
            'segment': self.segment,
            'transaction_type': leg.transaction_type,
            'product': leg.product,
            'order_type': leg.order_type,
            'quantity': leg.quantity,
            'price': leg.price,
            'filled_quantity': leg.filled_quantity,
            'average_price': leg.average_price,
            'decided_at': leg.decided_at,
            'answered_at': leg.answered_at,
            'decision_quote_time': self.quote_time(self.at_decision),
            'send_quote_time': self.quote_time(self.at_send),
            'answer_quote_time': self.quote_time(self.at_answer),
            'decision_mid': self.rounded(self.mid(self.at_decision)),
            'send_mid': self.rounded(self.mid(self.at_send)),
            'answer_mid': self.rounded(self.mid(self.at_answer)),
            'delay_cost': self.rounded(self.delay()),
            'latency_cost': self.rounded(self.latency()),
            'half_spread_cost': self.rounded(self.half_spread()),
            'beyond_touch_cost': self.rounded(self.beyond_touch()),
            'total_cost': self.rounded(self.total()),
            'total_cost_basis_points': self.basis_points(self.total()),
            'latency_cost_basis_points': self.basis_points(self.latency()),
            'total_cost_rupees': self.total_rupees(),
        }

    def quote_time(self, quote):
        """When a quote's tick was received.

        Args:
            quote (QuoteMoment | None): The quote.

        Returns:
            datetime.datetime | None: Its time, or None without a quote.
        """
        if quote is None:
            return None
        return quote.time

    def mid(self, quote):
        """A quote's mid-price.

        Args:
            quote (QuoteMoment | None): The quote.

        Returns:
            decimal.Decimal | None: Its mid-price, or None without a quote.
        """
        if quote is None:
            return None
        return quote.mid()

    def rounded(self, value):
        """A price rounded to the four places the table keeps.

        Args:
            value (decimal.Decimal | None): The price.

        Returns:
            decimal.Decimal | None: The rounded price, or None.
        """
        if value is None:
            return None
        return self.without_sign_on_zero(value.quantize(PRICE_PLACES))

    def without_sign_on_zero(self, value):
        """A figure with the minus sign taken off a zero, which a sell leg's unchanged price would otherwise carry.

        Args:
            value (decimal.Decimal): The figure.

        Returns:
            decimal.Decimal: The same figure, with a zero always positive.
        """
        if value == 0:
            return abs(value)
        return value
