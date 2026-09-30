"""Downloads IND Money's three instrument master files with an access token, served from memory instead of the network.

IND Money is the one broker here whose master is not public. `IndMoneyInstruments.download` asks the same endpoint three times, once for each `source` (`equity`, `fno` and `index`), with the access token in the `Authorization` header, reads each CSV answer as text and stacks them. The token is normally read from MongoDB when the ingester is built; passing `access_token` to the constructor, as this program does, uses that token instead and reads nothing.

The program must not download anything, so `requests.get` is replaced, only while `download` runs, by `InstrumentFileServer`, a stand-in that answers each source with a few recorded-looking lines and remembers what each request carried. Building the ingester creates a database engine, but the engine opens no connection until a query runs, and this program runs none.

Notice that all three requests carry the token given to the constructor, and that each source's rows follow the previous one's in the stacked frame.

Run it from the project root:

    python examples/stock_brokers/instruments/indmoney/IndMoneyInstruments/example_1_downloading_with_a_stored_token.py
"""

import unittest.mock

import requests

from stock_brokers.instruments.indmoney import (
    IndMoneyInstruments,
)

SOURCE_FILES = {
    'equity': (
        'exch,segment,security_id,instrument_name,trading_symbol,lot_units,tick_size,series,symbol_name,isin\n'
        'NSE,E,1594,EQUITY,INFY,1,0.1,EQ,INFOSYS LIMITED,INE009A01021\n'
        'BSE,E,500209,EQUITY,INFY,1,0.05,A,INFOSYS LTD,INE009A01021\n'
    ),
    'fno': (
        'exch,segment,security_id,instrument_name,trading_symbol,lot_units,tick_size,series,symbol_name,isin\n'
        'NSE,D,52175,FUTIDX,NIFTY-Oct2026-FUT,75,0.1,,NIFTY,\n'
    ),
    'index': (
        'exch,segment,security_id,instrument_name,trading_symbol,lot_units,tick_size,series,symbol_name,isin\n'
        'NSE,I,13,INDEX,NIFTY,1,0.05,,NIFTY 50,\n'
    ),
}


class InstrumentFileServer:
    """A stand-in for `requests.get` that answers each IND Money source with a canned CSV file.

    Attributes:
        files (dict): Each source mapped to the text of its CSV file.
        requests_made (list): The `source` parameter and `Authorization` header of every request, in order.
    """

    def __init__(self, files):
        """Holds the canned files.

        Args:
            files (dict): Each source mapped to the text of its CSV file.

        Returns:
            None: This method returns nothing.
        """
        self.files = files
        self.requests_made = []

    def get(self, url, params=None, headers=None, timeout=None):
        """Answers one source's request, in place of `requests.get`.

        Args:
            url (str): The instruments endpoint.
            params (dict | None): The query parameters, naming the source.
            headers (dict | None): The request headers, carrying the token.
            timeout (float | None): The timeout, which the stand-in ignores.

        Returns:
            requests.Response: A successful answer carrying the source's CSV file.
        """
        source = params['source']
        self.requests_made.append((source, headers['Authorization']))
        response = requests.Response()
        response.status_code = 200
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.encoding = 'utf-8'
        response._content = self.files[source].encode('utf-8')
        response.url = url
        return response


class DownloadingWithAStoredTokenExample:
    """Downloads the master with a given token and prints the requests and the rows.

    Attributes:
        server (InstrumentFileServer): The stand-in for IND Money's endpoint.
        instruments (IndMoneyInstruments): The ingester being shown.
    """

    def __init__(self):
        """Builds the stand-in server and the ingester with a token.

        Returns:
            None: This method returns nothing.
        """
        self.server = InstrumentFileServer(SOURCE_FILES)
        self.instruments = IndMoneyInstruments(access_token='indmoney-token-issued-today')

    def run(self):
        """Downloads the master and prints what each request carried and the rows returned.

        Returns:
            None: This method returns nothing.
        """
        with unittest.mock.patch.object(requests, 'get', self.server.get):
            frame = self.instruments.download()
        for source, authorization in self.server.requests_made:
            print(f'Requested source={source} with Authorization: {authorization}')
        print(f'Rows: {len(frame)}')
        print(frame.to_string())


if __name__ == '__main__':
    DownloadingWithAStoredTokenExample().run()
