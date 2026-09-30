"""Saves a leg as the document the parent's Redis record holds, and rebuilds it from that document.

A parent order keeps its legs in Redis as JSON, so every leg can turn itself into a plain dictionary with `document()` and back with `OrderLeg.from_document()`. Rebuilding copies every field the leg knows, ignores any field it does not, and treats a missing role as `entry`, which is how records written by an older engine still load.

The program saves a rejected stop leg, prints the document, rebuilds it and checks the two agree. It then rebuilds a short, older-style document that has no role and carries an extra field, to show those two rules.

No Redis client is needed, because the document is only a dictionary; the program uses `json` to show it survives the trip through text.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/order_leg/OrderLeg/example_2_saving_and_rebuilding_a_leg.py
"""

import json

from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)


class SavingAndRebuildingALegExample:
    """Round-trips one leg through its document and rebuilds an older record.

    Attributes:
        leg (OrderLeg): The leg that is saved.
    """

    def __init__(self):
        """Builds a stop-loss leg that Dhan rejected.

        Returns:
            None: This method returns nothing.
        """
        self.leg = OrderLeg('p-9e07:3', 'stop')
        self.leg.state = 'rejected'
        self.leg.broker = 'dhan'
        self.leg.instrument_id = 'NSE:SBIN'
        self.leg.transaction_type = 'SELL'
        self.leg.product = 'INTRADAY'
        self.leg.order_type = 'SL-M'
        self.leg.validity = 'DAY'
        self.leg.quantity = 50
        self.leg.trigger_price = 801.5
        self.leg.outcome = 'rejected'
        self.leg.status_message = 'Trigger price is above the last traded price'

    def run(self):
        """Prints the saved document and the rebuilt legs.

        Returns:
            None: This method returns nothing.
        """
        text = json.dumps(self.leg.document())
        print(f'Saved: {text}')
        rebuilt = OrderLeg.from_document(json.loads(text))
        print(f'Rebuilt matches: {rebuilt.document() == self.leg.document()}')
        print(f'Rebuilt: role={rebuilt.role} state={rebuilt.state} finished={rebuilt.is_finished()}')
        older_record = {
            'leg_id': 'p-0001:1',
            'state': 'sent',
            'broker': 'fyers',
            'broker_order_id': '52509300001234',
            'retired_field': 'ignored',
        }
        older_leg = OrderLeg.from_document(older_record)
        print(f'Older record: role={older_leg.role} state={older_leg.state} live={older_leg.is_live()}')
        print(f'Extra field kept: {"retired_field" in older_leg.document()}')


if __name__ == '__main__':
    SavingAndRebuildingALegExample().run()
