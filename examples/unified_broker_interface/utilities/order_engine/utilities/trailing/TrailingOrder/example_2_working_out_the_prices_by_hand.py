"""Works out a trailing stop's prices by hand for a short position, places the stop, and carries the trail on from a trigger the caller moved.

`TrailingOrder.on_price_tick` normally does all of this on each tick. This program calls each step on its own so its answer can be seen: which side the stop trades, how far behind the market it trails, where the trigger and the limit go, whether a price improves the watermark, and whether a new trigger has moved far enough, counting `step_ticks`, to be worth a modification.

The caller is short 40 shares, so `LongProtectionStop` protects the position with a buy stop above the market. The trail is `trail_percent` of 1 per cent, measured against the watermark, with a limit offset of 1.50 and a step of 4 ticks. It places the stop from a watermark of 2,400.00, and then pretends the caller moved the stop's trigger to 2,410.00 through `PUT /api/orders/modify`, which `on_leg_modified` answers by moving the watermark to the price whose trail lands on that trigger. With a percentage trail that price is a long unrounded decimal, and it is stored as it is. Finally it shows the refusals for a trail given both ways, for no trail, and for a number that is not above zero.

The engine's surroundings are the same stand-ins as in the first example: a placement that pretends Kotak accepted the order, an event log that keeps events in a list, and a parent store that ignores saves.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/trailing/TrailingOrder/example_2_working_out_the_prices_by_hand.py
"""

import decimal
import logging

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.trailing import (
    TrailingOrder,
)

INSTRUMENT_ID = '8e7d6c5b-4a39-4281-9f0e-1d2c3b4a5f6e'


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


class PricesByHandExample:
    """Calls each step of a buy-side trailing stop by hand.

    Attributes:
        event_log (ListEventLog): The stand-in event log.
        trailing (LongProtectionStop): The order being shown.
    """

    def __init__(self):
        """Builds a stop protecting a short of 40 shares.

        Returns:
            None: This method returns nothing.
        """
        parent = ParentOrder('7c1d2e3f-0000-4000-8000-000000000011')
        parent.synthetic_type = LongProtectionStop.SYNTHETIC_TYPE
        parent.instrument_id = INSTRUMENT_ID
        parent.body = {
            'instrument_id': INSTRUMENT_ID,
            'transaction_type': 'SELL',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 40,
        }
        parent.parameters = {
            'type': LongProtectionStop.SYNTHETIC_TYPE,
            'trail_percent': 1,
            'stop_limit_offset': '1.50',
            'step_ticks': 4,
            'tick_size': '0.05',
        }
        self.event_log = ListEventLog()
        quote = {
            'last_price': 2400.00,
        }
        self.trailing = LongProtectionStop(
            parent,
            StandInPlacement(quote),
            self.event_log,
            IgnoringParentStore(),
            logging.getLogger('example'),
        )

    def show_refusal(self, parameters, reading):
        """Prints the refusal for one set of parameters.

        Args:
            parameters (dict): The parameters to try.
            reading (str): Which reading to try: `trail` or `step`.

        Returns:
            None: This method returns nothing.
        """
        self.trailing.parent.parameters = parameters
        try:
            if reading == 'trail':
                self.trailing.read_trail(decimal.Decimal('2400'))
            else:
                self.trailing.read_step_ticks()
        except RefusedRequestError as error:
            print(f'  {parameters}: {error.status} {error.body["error"]}')

    def run(self):
        """Prints each step, places the stop, and follows the caller's change.

        Returns:
            None: This method returns nothing.
        """
        order = self.trailing.read_order(self.trailing.parent.body)
        side = self.trailing.leg_side(order.transaction_type)
        print(f'Caller is short, so the stop trades: {side}')
        start = decimal.Decimal('2400.00')
        print(f'Trail at 1% of {start}: {self.trailing.read_trail(start)}')
        print(f'Limit offset: {self.trailing.read_limit_offset()}, step: {self.trailing.read_step_ticks()} ticks')
        trigger = self.trailing.trigger_from(start, side)
        limit = self.trailing.limit_from(trigger, side)
        print(f'Trigger from {start}: {trigger}, limit: {limit}')
        stop = self.trailing.stop_order(order, trigger, limit, side)
        print(f'Stop order: {stop.transaction_type} {stop.order_type} {stop.quantity} trigger {stop.trigger_price} limit {stop.price}')
        print(f'Resting stop before placing: {self.trailing.resting_stop()}')

        view = MarketView(
            {
                'last_price': 2400.00,
            },
            self.trailing.tick_size(),
        )
        body, status = self.trailing.place_trailing_stop(order, view, start, None)
        leg = self.trailing.resting_stop()
        print(f'Placed: {status} {body["outcome"]}; leg {leg.leg_id} {leg.transaction_type} trigger {leg.trigger_price} limit {leg.price}; watermark {self.trailing.watermark()}')

        for price in [
            decimal.Decimal('2395.00'),
            decimal.Decimal('2402.00'),
        ]:
            print(f'Does {price} improve the watermark of a buy stop? {self.trailing.improves_watermark(price, self.trailing.watermark(), side)}')
        tick_size = self.trailing.tick_size()
        for new_trigger in [
            decimal.Decimal('2420.00'),
            decimal.Decimal('2423.90'),
        ]:
            print(f'Is moving the trigger to {new_trigger} worth it with a 4 tick step? {self.trailing.improves_trigger(new_trigger, leg, tick_size)}')

        before = {
            'trigger_price': leg.trigger_price,
        }
        leg.trigger_price = 2410.0
        self.trailing.on_leg_modified(leg, before)
        print(f'Caller moved the trigger to 2410.0; watermark is now {self.trailing.watermark()}')
        print(f'  recorded: {self.event_log.events[-1]["status_message"]}')
        watermark = self.trailing.watermark_for_trigger(decimal.Decimal('2410'), 'BUY')
        print(f'Watermark for a 2410 trigger, worked out directly: {watermark}')

        print(f'positive("2.5", "trail_points"): {self.trailing.positive("2.5", "trail_points")}')
        print('Refusals:')
        self.show_refusal(
            {
                'trail_points': 5,
                'trail_percent': 1,
            },
            'trail',
        )
        self.show_refusal(
            {},
            'trail',
        )
        self.show_refusal(
            {
                'trail_points': '-5',
            },
            'trail',
        )
        self.show_refusal(
            {
                'step_ticks': 0,
            },
            'step',
        )


if __name__ == '__main__':
    PricesByHandExample().run()
