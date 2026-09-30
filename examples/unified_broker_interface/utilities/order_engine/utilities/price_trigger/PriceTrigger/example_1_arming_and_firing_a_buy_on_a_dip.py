"""Arms a buy that waits for the price to fall to a level, then feeds it price ticks until it fires once.

`PriceTrigger` is the base class of every order type that waits for a price rather than for a fill, such as a market-if-touched or a hidden stop. A subclass only says what order to send when the level is reached, so this program defines a small one, `TouchBuyOrder`, which buys ten shares at the best offer once the last traded price falls to 995. Everything else shown here is the base class's own behaviour.

`run` records the parent and answers `202 armed` without sending anything. Each call to `on_price_tick` then reads the watched price and asks whether the level has been reached. The first tick at 1000.10 is above the level, the second at 994.90 reaches it and sends the child order, and the third, also below the level, sends nothing because the trigger fires only once.

The order engine's surroundings are stand-ins defined here: a placement object that pretends Zerodha accepted the order instead of calling it, an event log that keeps events in a list, and a parent store that only counts saves. The program also calls `arm`, `child_order` and `priced` directly, which `run` and `on_price_tick` normally call for you, to show what each returns.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/price_trigger/PriceTrigger/example_1_arming_and_firing_a_buy_on_a_dip.py
"""

import logging

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.price_trigger import (
    PriceTrigger,
)

INSTRUMENT_ID = '3f2a8c1e-5b7d-4e9a-8c6f-1d2e3f4a5b6c'


class TouchBuyOrder(PriceTrigger):
    """A buy that waits for the price to fall to a level and then takes the best offer."""

    SYNTHETIC_TYPE = 'touch_buy'
    ARMED_MESSAGE = 'the price falls to the level'

    def child_order(self, order, view):
        """A limit at the best offer, which fills against what is resting there.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            view (MarketView): The traded instrument's quote at the moment it fired.

        Returns:
            PlaceOrderRequest | None: The order to send, or None when there is no offer.
        """
        offer = view.opposite_touch(order.transaction_type)
        if offer is None:
            return None
        return self.priced(order, offer)


class StandInInstrument:
    """The catalogue entry the placement returns, holding each broker's order handle.

    Attributes:
        handles (dict): Each broker's handle, by broker name.
    """

    def __init__(self):
        """Builds an instrument that two brokers trade in ticks of 0.05.

        Returns:
            None: This method returns nothing.
        """
        self.handles = {
            'zerodha': {
                'tick_size': '0.05',
            },
            'dhan': {
                'tick_size': '0.05',
            },
        }


class StandInBrokerRequest:
    """The request built for a broker, as far as the event log reads it.

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


class StandInPlacement:
    """Stands in for `EnginePlacement`: it builds requests and answers for Zerodha without sending anything.

    Attributes:
        sent (list): The requests that were "sent".
    """

    def __init__(self):
        """Builds the stand-in with nothing sent.

        Returns:
            None: This method returns nothing.
        """
        self.sent = []

    def market_context(self, instrument_id, wants_quote, wants_positions):
        """Returns the instrument, and no quote or positions.

        Args:
            instrument_id (str): The instrument.
            wants_quote (bool): Whether the quote is needed.
            wants_positions (bool): Whether the positions are needed.

        Returns:
            tuple: The instrument (StandInInstrument), None and None.
        """
        return StandInInstrument(), None, None

    def prepare(self, order, instrument_id, broker_name=None):
        """Builds the request for Zerodha, or for the broker named.

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
            'quantity': order.quantity,
            'price': str(order.price),
        }
        return StandInPrepared(broker_name or 'zerodha', StandInBrokerRequest(fields))

    def send(self, prepared, started_at):
        """Pretends the broker accepted the order.

        Args:
            prepared (StandInPrepared): The prepared order.
            started_at (float): When the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        self.sent.append(prepared.broker_request.shown())
        body = {
            'broker': prepared.broker_name,
            'outcome': 'accepted',
            'order_id': '250930000000123',
            'status_message': 'the broker accepted the order',
        }
        return body, 200


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


class CountingParentStore:
    """Stands in for the Redis copy of the parent, only counting how often it is written.

    Attributes:
        saves (int): How many times the parent was saved.
    """

    def __init__(self):
        """Builds the stand-in.

        Returns:
            None: This method returns nothing.
        """
        self.saves = 0

    def save(self, parent):
        """Counts one save.

        Args:
            parent (ParentOrder): The parent.

        Returns:
            None: This method returns nothing.
        """
        self.saves = self.saves + 1


class BuyOnADipExample:
    """Arms a `TouchBuyOrder` at 995 and ticks it through three quotes.

    Attributes:
        placement (StandInPlacement): The stand-in placement.
        event_log (ListEventLog): The stand-in event log.
        parent_store (CountingParentStore): The stand-in parent store.
        trigger (TouchBuyOrder): The order being shown.
    """

    def __init__(self):
        """Builds the parent and the trigger.

        Returns:
            None: This method returns nothing.
        """
        parent = ParentOrder('7c1d2e3f-0000-4000-8000-000000000001')
        parent.synthetic_type = TouchBuyOrder.SYNTHETIC_TYPE
        parent.instrument_id = INSTRUMENT_ID
        parent.body = {
            'instrument_id': INSTRUMENT_ID,
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 10,
        }
        parent.parameters = {
            'type': TouchBuyOrder.SYNTHETIC_TYPE,
            'trigger_price': 995,
        }
        self.placement = StandInPlacement()
        self.event_log = ListEventLog()
        self.parent_store = CountingParentStore()
        self.trigger = TouchBuyOrder(
            parent,
            self.placement,
            self.event_log,
            self.parent_store,
            logging.getLogger('example'),
        )

    def quote(self, last_price, bid, offer):
        """Builds one live quote with one level on each side.

        Args:
            last_price (float): The last traded price.
            bid (float): The best bid.
            offer (float): The best offer.

        Returns:
            dict: The quote, keyed by instrument id as a price tick carries it.
        """
        return {
            INSTRUMENT_ID: {
                'last_price': last_price,
                'depth': {
                    'buy': [
                        {
                            'price': bid,
                            'quantity': 400,
                        },
                    ],
                    'sell': [
                        {
                            'price': offer,
                            'quantity': 250,
                        },
                    ],
                },
            },
        }

    def run(self):
        """Arms the order, ticks it, and prints what happened.

        Returns:
            None: This method returns nothing.
        """
        answer, status = self.trigger.run({}, 0.0)
        print(f'Answer {status}: outcome={answer["outcome"]} level={answer["trigger_level"]} direction={answer["trigger_direction"]}')
        print(f'  {answer["status_message"]}')
        print(f'Parent state {self.trigger.parent.state}, tick size kept {self.trigger.parent.parameters["tick_size"]}, sent so far {len(self.placement.sent)}')
        order = self.trigger.read_order(self.trigger.parent.body)
        print(f'Anything left resting while armed: {self.trigger.arm(order, 0.0)}')
        ticks = [
            (1759204800.0, self.quote(1000.10, 1000.05, 1000.10)),
            (1759204801.0, self.quote(994.90, 994.85, 994.95)),
            (1759204802.0, self.quote(993.00, 992.95, 993.05)),
        ]
        for moment, quotes in ticks:
            fired = self.trigger.on_price_tick(quotes, moment)
            last_price = quotes[INSTRUMENT_ID]['last_price']
            print(f'Tick at last price {last_price}: fired={fired} has_fired={self.trigger.has_fired()} state={self.trigger.parent.state}')
        print(f'Requests sent: {self.placement.sent}')
        print(f'Triggered at {self.trigger.parent.parameters["triggered_at"]} on price {self.trigger.parent.parameters["triggered_price"]}')
        for event in self.event_log.events:
            print(f'  event {event["sequence"]}: {event["event"]} parent_state={event.get("parent_state")} leg_state={event.get("leg_state")}')
        view = MarketView(self.quote(990.00, 989.95, 990.05)[INSTRUMENT_ID], self.trigger.tick_size())
        child = self.trigger.child_order(order, view)
        print(f'What it would send at a 990.05 offer: {child.order_type} {child.transaction_type} {child.quantity} at {child.price}')
        sell = self.trigger.priced(order, child.price, 'SELL')
        print(f'The same order priced as a sell: {sell.order_type} {sell.transaction_type} {sell.quantity} at {sell.price}')


if __name__ == '__main__':
    BuyOnADipExample().run()
