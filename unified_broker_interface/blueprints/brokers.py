"""
`/api/brokers`: each broker's registration and contact details, from the MongoDB `broker_details`
collection, one document per `broker_name`, served from its Redis copy
`unified:details:brokers` when `bin/unified/details` keeps one.
"""

from unified_broker_interface.blueprints.base import BaseBlueprint, authenticated

class BrokersBlueprint(BaseBlueprint):
    name = 'brokers'
    routes = [('/details', 'get_broker_details', ['GET'])]

    @authenticated
    def get_broker_details(self):
        """
        Details for every broker.
        """
        return self.list_collection('broker_details', 'unified:details:brokers', 'Broker details not found')

brokers_bp = BrokersBlueprint().blueprint
