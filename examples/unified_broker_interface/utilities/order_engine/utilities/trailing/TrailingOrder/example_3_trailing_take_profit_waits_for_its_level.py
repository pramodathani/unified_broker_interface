"""Arms a trailing take-profit that places nothing until the market reaches its level, and shows the refusal when there is no price to trail from.

With `activate_at`, a `TrailingOrder` becomes a trailing take-profit: `run` records the parent and answers `202 armed` without placing a stop, and each price tick asks whether the market has reached the level. Once it has, the stop is placed a trail behind that price and trails from there, so the position exits on the first pullback after the target instead of at the target itself.

The caller is long 25 INFY and asks for activation at 1,050.00 with a 5 rupee trail. The ticks at 1,030.00 and 1,049.95 place nothing. The program then calls `read_activation` and `activation_reached` itself, and hands `activate` the tick at 1,052.00 directly, which is what `on_price_tick` does while no stop has been placed. The next tick, at 1,060.00, is an ordinary trailing move.

A second parent without `activate_at` is armed while the live quote has no last traded price, which is refused with HTTP 503, because there is nothing to measure the trail from. The stand-ins are the same as in the first example: a placement that pretends Kotak accepted each order and modification, an event log that keeps events in a list, and a parent store that ignores saves.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/trailing/TrailingOrder/example_3_trailing_take_profit_waits_for_its_level.py
"""

import decimal
import logging

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.trailing import (
    TrailingOrder,
)

INSTRUMENT_ID = '3f2a8c1e-5b7d-4e9a-8c6f-1d2e3f4a5b6c'


class LongProtectionStop(TrailingOrder):
    """A trailing stop that protects a position opened with the caller's side, by trading the other side."""

    SYNTHETIC_TYPE = 'long_protection_stop'
    ARMED_STATE = 'protecting'

    def leg_side(self, transaction_type):
        """The side that closes the position.

        Args:
            transaction_type (str): The side that opened the position.

        Returns:
            str: SELL to protect a long, BUY to protect a short.
        """
        if transaction_type == 'BUY':
            return 'SELL'
        return 'BUY'


class StandInInstrument:
    """The catalogue entry the placement returns.

    Attributes:
        handles (dict): Each broker's handle, by broker name.
    """

    def __init__(self):
        """Builds an instrument traded in ticks of 0.05.

        Returns:
            None: This method returns nothing.
        """
        self.handles = {
            'kotak': {
                'tick_size': '0.05',
            },
        }


class StandInBrokerRequest:
    """The request built for a broker.

    Attributes:
        tag (str | None): The tag the request carries.
        fields (dict): What would be sent.
    """

    def __init__(self, fields):
        """Builds the request.

        Args:
            fields (dict): What would be sent.

        Returns:
            None: This method returns nothing.
        """
        self.tag = None
        self.fields = fields

    def shown(self):
        """The request as the event log keeps it.

        Returns:
            dict: The fields.
        """
        return self.fields


class StandInPrepared:
    """An order with a broker chosen and its request built.

    Attributes:
        broker_name (str): The chosen broker.
        broker_request (StandInBrokerRequest): The request.
        identifier_sent (str): The symbol the request names.
    """

    def __init__(self, broker_name, broker_request):
        """Builds the prepared order.

        Args:
            broker_name (str): The chosen broker.
            broker_request (StandInBrokerRequest): The request.

        Returns:
            None: This method returns nothing.
        """
        self.broker_name = broker_name
        self.broker_request = broker_request
        self.identifier_sent = 'INFY'


class StandInModifyAnswer:
    """What a broker said to a modification.

    Attributes:
        outcome (str): accepted.
        status_message (str | None): The broker's message.
        response_body (dict): The broker's reply.
    """

    def __init__(self):
        """Builds an accepted answer.

        Returns:
            None: This method returns nothing.
        """
        self.outcome = 'accepted'
        self.status_message = None
        self.response_body = {
            'stat': 'Ok',
        }


class StandInPlacement:
    """Stands in for `EnginePlacement`: Kotak accepts every placement and modification, and nothing is sent.

    Attributes:
        quote (dict): The live quote `market_context` returns.
    """

    def __init__(self, quote):
        """Builds the stand-in.

        Args:
            quote (dict): The live quote `market_context` returns.

        Returns:
            None: This method returns nothing.
        """
        self.quote = quote

    def market_context(self, instrument_id, wants_quote, wants_positions):
        """Returns the instrument and the live quote.

        Args:
            instrument_id (str): The instrument.
            wants_quote (bool): Whether the quote is needed.
            wants_positions (bool): Whether the positions are needed.

        Returns:
            tuple: The instrument (StandInInstrument), the quote (dict) and None.
        """
        return StandInInstrument(), self.quote, None

    def prepare(self, order, instrument_id, broker_name=None):
        """Builds the request for Kotak.

        Args:
            order (PlaceOrderRequest): The order.
            instrument_id (str): The instrument.
            broker_name (str | None): The broker the order must go to.

        Returns:
            StandInPrepared: The prepared order.
        """
        fields = {
            'transaction_type': order.transaction_type,
            'order_type': order.order_type,
            'price': str(order.price),
            'trigger_price': str(order.trigger_price),
        }
        return StandInPrepared(broker_name or 'kotak', StandInBrokerRequest(fields))

    def send(self, prepared, started_at):
        """Answers as a broker that accepted the order.

        Args:
            prepared (StandInPrepared): The prepared order.
            started_at (float): When the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        print(f'  sent to {prepared.broker_name}: {prepared.broker_request.shown()}')
        body = {
            'broker': prepared.broker_name,
            'outcome': 'accepted',
            'order_id': '250930000000456',
            'status_message': 'the broker accepted the order',
        }
        return body, 200

    def modify_leg(self, broker_name, broker_order_id, price=None, trigger_price=None):
        """Answers as a broker that accepted a modification.

        Args:
            broker_name (str): The broker.
            broker_order_id (str): The order to modify.
            price (decimal.Decimal | None): The new limit.
            trigger_price (decimal.Decimal | None): The new trigger.

        Returns:
            StandInModifyAnswer: The answer.
        """
        print(f'  modify {broker_name} {broker_order_id}: trigger {trigger_price}, limit {price}')
        return StandInModifyAnswer()


class ListEventLog:
    """Stands in for the event log, keeping every event in a list.

    Attributes:
        events (list): The events recorded, oldest first.
    """

    def __init__(self):
        """Builds an empty log.

        Returns:
            None: This method returns nothing.
        """
        self.events = []

    def record(self, event):
        """Keeps one event.

        Args:
            event (dict): The event.

        Returns:
            None: This method returns nothing.
        """
        self.events.append(event)


class IgnoringParentStore:
    """Stands in for the Redis copy of the parent, and writes nothing."""

    def save(self, parent):
        """Ignores one save.

        Args:
            parent (ParentOrder): The parent.

        Returns:
            None: This method returns nothing.
        """


class TakeProfitExample:
    """Arms a trailing take-profit, ticks it up to its level and beyond, and shows one refusal."""

    def trailing(self, parameters, quote):
        """Builds a stop protecting a long of 25 shares.

        Args:
            parameters (dict): The parent's parameters.
            quote (dict): The live quote the placement returns.

        Returns:
            LongProtectionStop: The order.
        """
        parent = ParentOrder('7c1d2e3f-0000-4000-8000-000000000012')
        parent.synthetic_type = LongProtectionStop.SYNTHETIC_TYPE
        parent.instrument_id = INSTRUMENT_ID
        parent.body = {
            'instrument_id': INSTRUMENT_ID,
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 25,
        }
        parent.parameters = parameters
        return LongProtectionStop(
            parent,
            StandInPlacement(quote),
            ListEventLog(),
            IgnoringParentStore(),
            logging.getLogger('example'),
        )

    def ticked(self, last_price):
        """Builds the quotes one tick carries.

        Args:
            last_price (float): The last traded price.

        Returns:
            dict: The quote, keyed by instrument id.
        """
        return {
            INSTRUMENT_ID: {
                'last_price': last_price,
            },
        }

    def run(self):
        """Arms the take-profit, ticks it, and shows the refusal.

        Returns:
            None: This method returns nothing.
        """
        take_profit = self.trailing(
            {
                'type': LongProtectionStop.SYNTHETIC_TYPE,
                'trail_points': 5,
                'stop_limit_offset': 1,
                'activate_at': 1050,
            },
            None,
        )
        answer, status = take_profit.run({}, 0.0)
        print(f'Answer {status}: outcome={answer["outcome"]} activate_at={answer["activate_at"]}')
        print(f'  {answer["status_message"]}')
        print(f'Activation level: {take_profit.read_activation()}')
        for last_price in [
            1030.00,
            1049.95,
        ]:
            placed = take_profit.on_price_tick(self.ticked(last_price), 1759204800.0)
            print(f'Tick at {last_price:.2f}: stop placed={placed}, legs={len(take_profit.parent.legs)}')
        reached = take_profit.activation_reached(decimal.Decimal('1052.00'), 'SELL')
        print(f'Has 1052.00 reached the level for a sell stop? {reached}')
        print('Handing activate the tick at 1052.00:')
        placed = take_profit.activate(self.ticked(1052.00))
        stop = take_profit.resting_stop()
        print(f'  placed={placed} parent state={take_profit.parent.state} trigger={stop.trigger_price} limit={stop.price} watermark={take_profit.watermark()}')
        print('Tick at 1060.00:')
        moved = take_profit.on_price_tick(self.ticked(1060.00), 1759204803.0)
        print(f'  moved={moved} trigger={stop.trigger_price} limit={stop.price} watermark={take_profit.watermark()}')

        no_price = self.trailing(
            {
                'type': LongProtectionStop.SYNTHETIC_TYPE,
                'trail_points': 5,
                'stop_limit_offset': 1,
            },
            {
                'depth': {},
            },
        )
        try:
            no_price.run({}, 0.0)
        except RefusedRequestError as error:
            print(f'Armed with no last price: {error.status} {error.body["error"]}')


if __name__ == '__main__':
    TakeProfitExample().run()
