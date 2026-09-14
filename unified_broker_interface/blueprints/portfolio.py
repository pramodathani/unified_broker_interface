"""
`/api/portfolio`: the account's funds, holdings and positions across every broker, from the documents the `bin/unified/`
scripts keep in Redis.

| Route | Answers from | Written |
| --- | --- | --- |
| `/funds` | `unified:portfolio:funds`, by `bin/unified/funds` | every half second |
| `/holdings` | `unified:portfolio:holdings`, by `bin/unified/holdings`, priced by `unified:quotes:live` | every minute |
| `/positions` | `unified:portfolio:positions`, by `bin/unified/positions`, priced by `unified:quotes:live` | every half second |

Nothing here asks a broker: each broker's own scripts keep its data in Redis, and the unified scripts combine it in this
API's shape, with `as_of` and each broker's read status. See `utilities/unified_documents.py` for when a document is not
served.
"""

from flask import jsonify

from unified_broker_interface.blueprints.base import BaseBlueprint, authenticated
from unified_broker_interface.utilities.unified_documents import read_document

class PortfolioBlueprint(BaseBlueprint):
    name = 'portfolio'
    routes = [
        ('/funds', 'funds', ['GET']),
        ('/holdings', 'holdings', ['GET']),
        ('/positions', 'positions', ['GET']),
    ]

    @authenticated
    def funds(self):
        """
        The account's funds summed across every broker, with how each broker's data was read.
        """
        body, status = read_document(self.cache, 'unified:portfolio:funds', 30, 'funds')
        return jsonify(body), status

    @authenticated
    def holdings(self):
        """
        The account's holdings merged across every broker and priced, with how each broker's data was read.

        Written every minute, so a document up to five minutes old is served.
        """
        body, status = read_document(self.cache, 'unified:portfolio:holdings', 300, 'holdings')
        return jsonify(body), status

    @authenticated
    def positions(self):
        """
        The account's open positions merged across every broker and priced, net and day, with how each broker's data
        was read.
        """
        body, status = read_document(self.cache, 'unified:portfolio:positions', 30, 'positions')
        return jsonify(body), status

portfolio_bp = PortfolioBlueprint().blueprint
