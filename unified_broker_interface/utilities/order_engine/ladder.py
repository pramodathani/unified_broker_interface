"""Several limit orders spaced across a price range, to average into a position rather than guess one price."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder


class Ladder(SyntheticOrder):
    """Places `steps` limit orders evenly spaced between two prices.

    Somebody who thinks an instrument is worth buying between 995 and 1000 does not have to choose which of those two numbers to bid. A ladder bids at both and at the prices between, so the average paid depends on how far the market comes rather than on one guess made in advance.

    Every rung goes to the same broker, chosen once, for the same reason a sliced order does: a position spread across brokers takes one order per broker to close, and each of those has its own lot size and its own freeze limit.

    Every rung's price is rounded to the tick towards the passive side, so a range that does not divide evenly into ticks produces rungs that rest rather than crossing.

    The caller's `quantity` is the whole order and is divided between the rungs as evenly as whole units allow, so a ladder of 100 over three rungs is 34, 33 and 33 rather than three of 100.
    """

    SYNTHETIC_TYPE = 'ladder'
    MOST_STEPS = 20

    def run(self, intent, started_at):
        """Places every rung of the ladder and answers with what they did.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For an order answered without calling a broker.
        """
        order = self.read_order(self.parent.body)
        parameters = self.parent.parameters
        instrument, _, _ = self.placement.market_context(
            self.parent.instrument_id,
            False,
            False,
        )
        tick_size = order.agreed_tick_size(instrument.handles)
        if tick_size is None:
            raise RefusedRequestError.refusal(
                'a ladder needs a tick size the brokers agree on and there is '
                'none for this instrument',
                503,
                instrument_id=self.parent.instrument_id,
            )
        rungs = self.rungs(order, parameters, tick_size)

        if order.dry_run:
            prepared = self.placement.prepare(
                rungs[0],
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.record_received()
        self.save()

        answers = []
        broker_name = None
        for rung in rungs:
            body, status, leg_id = self.place_leg(
                'slice',
                rung,
                started_at,
                broker_name,
            )
            if broker_name is None:
                broker_name = body.get('broker')
            answers.append((body, status))
        self.finish(answers)
        return self.answer(answers, broker_name, rungs)

    def rungs(self, order, parameters, tick_size):
        """One order per rung, priced across the range and sharing the quantity.

        Args:
            order (PlaceOrderRequest): The validated order.
            parameters (dict): The caller's `synthetic` object, with `from_price`, `to_price` and `steps`.
            tick_size (decimal.Decimal): The instrument's tick size.

        Returns:
            list: One `PlaceOrderRequest` per rung, cheapest first for a buy.

        Raises:
            RefusedRequestError: With HTTP 400 when the range or the number of steps is not usable.
        """
        steps = self.whole(parameters.get('steps'), 'steps')
        if steps < 2 or steps > self.MOST_STEPS:
            raise RefusedRequestError.refusal(
                f'a ladder needs steps between 2 and {self.MOST_STEPS}, '
                f'not {steps}',
                400,
            )
        if order.quantity < steps:
            raise RefusedRequestError.refusal(
                f'a ladder of {steps} steps needs a quantity of at least '
                f'{steps}, not {order.quantity}',
                400,
            )
        from_price = self.price(parameters, 'from_price')
        to_price = self.price(parameters, 'to_price')
        if from_price == to_price:
            raise RefusedRequestError.refusal(
                'a ladder needs from_price and to_price to differ',
                400,
            )

        span = to_price - from_price
        each = order.quantity // steps
        remainder = order.quantity - each * steps
        rungs = []
        for index in range(steps):
            fraction = decimal.Decimal(index) / decimal.Decimal(steps - 1)
            price = order.rounded_to_tick(
                from_price + span * fraction,
                tick_size,
                order.transaction_type,
            )
            quantity = each + (1 if index < remainder else 0)
            rung = order.with_quantities(quantity, 0)
            rung.price = price
            rung.price_text = str(price)
            rung.price_number = float(price)
            rungs.append(rung)
        return rungs

    def price(self, parameters, field_name):
        """One end of the ladder's range.

        Args:
            parameters (dict): The caller's `synthetic` object.
            field_name (str): `from_price` or `to_price`.

        Returns:
            decimal.Decimal: The price.

        Raises:
            RefusedRequestError: With HTTP 400 when the price is missing or not above zero.
        """
        try:
            price = decimal.Decimal(str(parameters.get(field_name)))
        except (decimal.InvalidOperation, TypeError):
            price = None
        if price is None or not price.is_finite() or price <= 0:
            raise RefusedRequestError.refusal(
                f'a ladder needs {field_name} above zero',
                400,
            )
        return price

    def whole(self, value, field_name):
        """One of the ladder's whole-number settings.

        Args:
            value (object): The value.
            field_name (str): Its name, for the message.

        Returns:
            int: The number.

        Raises:
            RefusedRequestError: With HTTP 400 when the value is not a whole number.
        """
        try:
            return int(value)
        except (TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'a ladder needs {field_name} as a whole number',
                400,
            )

    def finish(self, answers):
        """Records the parent's state from what the rungs did.

        Args:
            answers (list): One `(body, status)` per rung.

        Returns:
            None: This method returns nothing.
        """
        outcomes = [body.get('outcome') for body, _ in answers]
        if 'unknown' in outcomes:
            state = 'failed'
        elif 'accepted' in outcomes:
            state = 'working'
        else:
            state = 'rejected'
        self.record_state(state, None)
        self.save()

    def answer(self, answers, broker_name, rungs):
        """The one answer the waiting API worker gets for a ladder.

        Args:
            answers (list): One `(body, status)` per rung.
            broker_name (str | None): The broker every rung went to.
            rungs (list): The orders that were sent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        bodies = [body for body, _ in answers]
        statuses = [status for _, status in answers]
        outcomes = [body.get('outcome') for body in bodies]
        outcome = 'accepted'
        if 'unknown' in outcomes:
            outcome = 'unknown'
        elif 'rejected' in outcomes:
            outcome = 'rejected'
        return {
            'broker': broker_name,
            'instrument_id': self.parent.instrument_id,
            'parent_id': self.parent.parent_order_id,
            'tag': self.parent.tag,
            'outcome': outcome,
            'order_ids': [body.get('order_id') for body in bodies],
            'rungs': [
                {
                    'price': float(rung.price),
                    'quantity': rung.quantity,
                }
                for rung in rungs
            ],
            'skipped': bodies[0].get('skipped') if bodies else [],
            'timing_ms': bodies[0].get('timing_ms') if bodies else {},
        }, max(statuses) if statuses else 200
