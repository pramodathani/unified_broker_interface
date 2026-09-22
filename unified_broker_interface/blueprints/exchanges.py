"""
`/api/exchanges`: each exchange's profile, from the MongoDB `exchange_details` collection, one
document per `exchange` (`nse`, `bse`, `mcx`, `ncdex`), served from its Redis copy
`unified:details:exchanges` when `bin/unified/user/unified_details` keeps one.
"""

from unified_broker_interface.blueprints.base import BaseBlueprint, authenticated

class ExchangesBlueprint(BaseBlueprint):
    name = 'exchanges'
    routes = [('/details', 'get_exchange_details', ['GET'])]

    @authenticated
    def get_exchange_details(self):
        """
        Details for every exchange.
        """
        return self.list_collection('exchange_details', 'unified:details:exchanges', 'Exchange details not found')

exchanges_bp = ExchangesBlueprint().blueprint
