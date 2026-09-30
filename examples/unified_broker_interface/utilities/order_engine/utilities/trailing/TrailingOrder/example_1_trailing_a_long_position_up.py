"""Places a trailing stop under a long position and follows a rising market with it, never moving it back down.

`TrailingOrder` is the mechanism behind both trailing types: a stop-loss limit rests at the broker, and each price tick that sets a new best price moves the stop up behind it. A subclass only says which side the stop trades on, so this program defines `LongProtectionStop`, which protects a long position with a sell stop, as the real trailing stop type does.

The caller holds INFY bought at about 1,000 and asks for a stop 10 rupees behind the market, with its limit 2 rupees past the trigger. `run` reads the last traded price of 1,000.00 from the quote and places a stop triggering at 990.00 with a limit at 988.00. The ticks then go to 1,004.00, back to 1,001.00, to 1,020.00, and back down to 1,012.00. Notice that the stop only moves on the two ticks that set a new high, and that the watermark stays at 1,020.00 during the pullback.

The engine's surroundings are stand-ins defined here: a placement object that pretends Kotak accepted each placement and modification instead of calling it, an event log that keeps events in a list, and a parent store that ignores saves. No risk gates are passed, so every modification goes straight through.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/trailing/TrailingOrder/example_1_trailing_a_long_position_up.py
"""

import logging

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


class TrailingLongExample:
    """Places a trailing stop under a long position and ticks it through a rise and two pullbacks.

    Attributes:
        trailing (LongProtectionStop): The order being shown.
    """

    def __init__(self):
        """Builds the parent, the stand-ins and the order.

        Returns:
            None: This method returns nothing.
        """
        parent = ParentOrder('7c1d2e3f-0000-4000-8000-000000000010')
        parent.synthetic_type = LongProtectionStop.SYNTHETIC_TYPE
        parent.instrument_id = INSTRUMENT_ID
        parent.body = {
            'instrument_id': INSTRUMENT_ID,
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 25,
        }
        parent.parameters = {
            'type': LongProtectionStop.SYNTHETIC_TYPE,
            'trail_points': 10,
            'stop_limit_offset': 2,
        }
        self.trailing = LongProtectionStop(
            parent,
            StandInPlacement(self.quote(1000.00)),
            ListEventLog(),
            IgnoringParentStore(),
            logging.getLogger('example'),
        )

    def quote(self, last_price):
        """Builds one live quote around a last traded price.

        Args:
            last_price (float): The last traded price.

        Returns:
            dict: The quote.
        """
        return {
            'last_price': last_price,
            'depth': {
                'buy': [
                    {
                        'price': last_price - 0.05,
                        'quantity': 500,
                    },
                ],
                'sell': [
                    {
                        'price': last_price + 0.05,
                        'quantity': 500,
                    },
                ],
            },
        }

    def run(self):
        """Places the stop and ticks it, printing the stop after each tick.

        Returns:
            None: This method returns nothing.
        """
        print('Placing the stop:')
        answer, status = self.trailing.run({}, 0.0)
        print(f'Answer {status}: outcome={answer["outcome"]} watermark={answer["watermark"]} parent state={self.trailing.parent.state}')
        moment = 1759204800.0
        for last_price in [
            1004.00,
            1001.00,
            1020.00,
            1012.00,
        ]:
            moment = moment + 1
            print(f'Tick at {last_price:.2f}:')
            quotes = {
                INSTRUMENT_ID: self.quote(last_price),
            }
            moved = self.trailing.on_price_tick(quotes, moment)
            stop = self.trailing.resting_stop()
            print(f'  moved={moved} watermark={self.trailing.watermark()} stop trigger={stop.trigger_price} limit={stop.price}')


if __name__ == '__main__':
    TrailingLongExample().run()
