"""Two legs entered at a target net price, the hard one first."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder
from unified_broker_interface.utilities.order_engine.utilities.candidate_legs import (
    CandidateLegs,
)

DEFAULT_BUFFER_TICKS = 2


class LeggedSpread(SyntheticOrder):
    """A two-legged position put on for a stated net price, by working one leg and taking the other.

    A vertical spread, a calendar roll, a futures-and-options hedge. What the trader cares about is not either leg's price but the difference between them: pay two rupees net for the spread, receive eighty net for the condor's wings. The two legs are almost never equally liquid, so the way to get that net is to rest a passive limit on the hard leg and, the moment it fills, take the easy one at whatever price makes the arithmetic work.

    **The first candidate is the leg that gets worked**, and which one that is matters twice over. It should be the less liquid leg, because that is the one that needs patience. And for Indian futures and options margin it should be the leg you are **buying**, because buying the hedge before selling the short leg gets the spread's margin benefit, where the other order briefly demands the full margin for a naked short and can be refused for it.

    `net_price` is the net debit per unit: positive when the spread costs money, negative when it brings money in. Once the worked leg fills at an average price, the second leg's price follows from arithmetic — whatever makes the two add up to the net — and that price is the worst this will accept. If the market is already better than that, the better price is taken instead and the net comes out ahead of target.

    **This is legging risk and there is no way around it.** Only an exchange's own multi-leg order can guarantee both legs at a net price, and the Indian exchanges' spread products are not reachable through these brokers' APIs. Between the first leg filling and the second, the market can move, and the position can end up one-legged at a net nobody wanted. What is done about it is to work the illiquid leg — the one that would be hard to unwind — so that the leg left exposed is the one that can be dealt with quickly.
    """

    SYNTHETIC_TYPE = 'legged_spread'

    def read_net_price(self):
        """The net debit per unit this spread is aiming at.

        Returns:
            decimal.Decimal: The net, positive when the spread costs money.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or is not a number.
        """
        value = self.parent.parameters.get('net_price')
        if value is None:
            raise RefusedRequestError.refusal(
                'a legged spread needs net_price, the net debit per unit it '
                'is aiming at',
                400,
            )
        try:
            return decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'net_price must be a number, not {value!r}',
                400,
            )

    def read_legs(self):
        """The two legs, the one to work first.

        Returns:
            list: Two `(instrument_id, body)` pairs.

        Raises:
            RefusedRequestError: With HTTP 400 when there are not exactly two.
        """
        candidates = CandidateLegs().read(
            self.parent.parameters,
            self.parent.body,
        )
        if len(candidates) != 2:
            raise RefusedRequestError.refusal(
                'a legged spread has exactly two legs, the one to work first; '
                f'{len(candidates)} were given',
                400,
            )
        return candidates

    def signed(self, price, transaction_type):
        """One leg's price as it contributes to the net, negative for a sale.

        Args:
            price (decimal.Decimal): The leg's price.
            transaction_type (str): BUY or SELL.

        Returns:
            decimal.Decimal: The signed price.
        """
        return price if transaction_type == 'BUY' else -price

    def second_leg_price(self, filled_at, worked_side, other_side):
        """What the second leg has to trade at for the net to come out right.

        Args:
            filled_at (decimal.Decimal): The average price the worked leg filled at.
            worked_side (str): BUY or SELL, the worked leg's side.
            other_side (str): BUY or SELL, the second leg's side.

        Returns:
            decimal.Decimal: The price, before it is rounded or improved on.
        """
        wanted = self.read_net_price() - self.signed(filled_at, worked_side)
        return wanted if other_side == 'BUY' else -wanted

    def run(self, intent, started_at):
        """Rests the worked leg and waits for it to fill.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when the net price or the two legs cannot be read.
        """
        order = self.read_order(self.parent.body)
        self.read_net_price()
        legs = self.read_legs()
        worked_instrument, worked_body = legs[0]
        worked_order = self.read_order(worked_body)

        if order.dry_run:
            prepared = self.placement.prepare(worked_order, worked_instrument)
            return self.placement.dry_run_answer(prepared, started_at)

        self.remember_tick_size(worked_order)
        self.record_received()
        self.save()
        body, status, _ = self.place_leg(
            'worked',
            worked_order,
            started_at,
            None,
            worked_instrument,
        )
        outcome = body.get('outcome')
        state = {
            'accepted': 'working',
            'rejected': 'rejected',
        }.get(outcome, 'failed')
        self.record_state(state, body.get('status_message'))
        self.save()
        body['parent_id'] = self.parent.parent_order_id
        body['net_price'] = str(self.read_net_price())
        return body, status

    def on_leg_update(self, leg, changes):
        """Sends the second leg as soon as the worked one starts filling.

        The second leg is sized to what has actually filled, and it is sent on the first partial fill rather than waiting for the whole of the first leg. Waiting would leave the filled part of a spread one-legged for as long as the rest of the worked leg takes, which on an illiquid strike can be the rest of the afternoon.

        Args:
            leg (OrderLeg): The leg that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        if leg.role != 'worked' or not leg.filled_quantity:
            return
        hedged = self.parent.parameters.get('hedged_quantity') or 0
        wanted = leg.filled_quantity - hedged
        if wanted < 1:
            return
        legs = self.read_legs()
        other_instrument, other_body = legs[1]
        other_body = dict(other_body)
        other_body['quantity'] = wanted
        other_order = self.read_order(other_body)

        price = self.price_for(leg, other_order, other_instrument)
        if price is None:
            return
        other_body['order_type'] = 'LIMIT'
        other_body['price'] = str(price)
        self.parent.parameters = dict(self.parent.parameters)
        self.parent.parameters['hedged_quantity'] = hedged + wanted
        self.save()
        self.place_leg(
            'other',
            self.read_order(other_body),
            None,
            self.chosen_broker(),
            other_instrument,
        )
        self.save()

    def price_for(self, worked_leg, other_order, other_instrument):
        """The price the second leg goes out at: the arithmetic one, or better if the market offers it.

        Args:
            worked_leg (OrderLeg): The leg that filled.
            other_order (PlaceOrderRequest): The second leg's order.
            other_instrument (str): The second leg's instrument.

        Returns:
            decimal.Decimal | None: The price, or None when it works out at zero or below.
        """
        filled_at = decimal.Decimal(
            str(worked_leg.average_price or worked_leg.price or 0),
        )
        if filled_at <= 0:
            return None
        needed = self.second_leg_price(
            filled_at,
            worked_leg.transaction_type,
            other_order.transaction_type,
        )
        if needed <= 0:
            return None
        return needed

