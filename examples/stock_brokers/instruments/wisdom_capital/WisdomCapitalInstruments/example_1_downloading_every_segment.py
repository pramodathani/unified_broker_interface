"""Downloads Wisdom Capital's instrument master for every exchange segment, from canned answers instead of the network.

Wisdom Capital serves its master through a POST endpoint, one call per exchange segment. The answer is JSON whose `result` field holds pipe-delimited lines with no header, and a line has 22, 23 or 21 fields depending on whether it is an equity, an option or a future. `WisdomCapitalInstruments.download` sorts the lines into those three shapes by the instrument type in the third field, names each shape's columns, and stacks them with a `data_category` column saying which shape each row was read as. A segment answered with an empty `result` is reported and skipped, because the broker does that for a segment it is not publishing that day.

The program must not download anything, so the module's `build_session` is replaced, only while `download` runs, by one that returns `RecordedMasterSession`, a stand-in whose `post` answers each segment with a few recorded-looking lines and remembers which segments were asked for. Building the ingester creates a database engine, but the engine opens no connection until a query runs, and this program runs none.

Notice the segments reported as empty, and that the future, the option and the equity each come back with their own shape's columns filled in.

Run it from the project root:

    python examples/stock_brokers/instruments/wisdom_capital/WisdomCapitalInstruments/example_1_downloading_every_segment.py
"""

import json
import unittest.mock

import requests

from stock_brokers.instruments import wisdom_capital as wisdom_capital_instruments
from stock_brokers.instruments.wisdom_capital import (
    WisdomCapitalInstruments,
)

SEGMENT_ANSWERS = {
    'NSECM': (
        'NSECM|2885|8|RELIANCE|RELIANCE-EQ|EQ|RELIANCE-EQ|1100100002885|1545.3|1264.3|50001|0.1|1|1|RELIANCE|INE002A01018|1|1|RELIANCE INDUSTRIES LTD|0|-1|-1\n'
        'NSECM|1594|8|INFY|INFY-EQ|EQ|INFY-EQ|1100100001594|1650.2|1350.2|50001|0.1|1|1|INFY|INE009A01021|1|1|INFOSYS LIMITED|0|-1|-1\n'
    ),
    'NSEFO': (
        'NSEFO|35001|1|NIFTY|NIFTY26OCTFUT|FUTIDX|FUTIDX-NIFTY|2600000035001|27500|22500|1801|0.1|75|1|-1|NIFTY|2026-10-27T14:30:00|NIFTY 27OCT FUT|1|1|NIFTY 26 OCT FUT\n'
        'NSEFO|40001|2|NIFTY|NIFTY26OCT25000CE|OPTIDX|OPTIDX-NIFTY|2600000040001|1200|0.05|1801|0.05|75|1|-1|NIFTY|2026-10-27T14:30:00|25000|3|NIFTY 27OCT 25000 CE|1|1|NIFTY 26 OCT 25000 CE\n'
    ),
    'MCXFO': (
        'MCXFO|451669|1|CRUDEOIL|CRUDEOIL26OCTFUT|FUTCOM|FUTCOM-CRUDEOIL|5100000451669|7200|5400|10000|1|100|1|-1|CRUDEOIL|2026-10-19T23:30:00|CRUDEOIL 19OCT FUT|1|1|CRUDEOIL 26 OCT FUT\n'
    ),
}


class RecordedMasterSession:
    """A stand-in for the `requests` session `download` posts through, answering each segment with canned lines.

    Attributes:
        answers (dict): Each exchange segment mapped to the pipe-delimited text of its master.
        segments_asked (list): Every segment requested, in order.
    """

    def __init__(self, answers):
        """Holds the canned answers.

        Args:
            answers (dict): Each exchange segment mapped to the pipe-delimited text of its master.

        Returns:
            None: This method returns nothing.
        """
        self.answers = answers
        self.segments_asked = []

    def post(self, url, headers=None, json=None, timeout=None):
        """Answers one segment's request as Wisdom Capital does, with the lines in the `result` field.

        Args:
            url (str): The master endpoint.
            headers (dict | None): The request headers.
            json (dict | None): The request body, naming the segment in `exchangeSegmentList`.
            timeout (float | None): The timeout, which the stand-in ignores.

        Returns:
            requests.Response: A successful answer, with an empty `result` for a segment that has no canned lines.
        """
        segment = json['exchangeSegmentList'][0]
        self.segments_asked.append(segment)
        body = {
            'type': 'success',
            'code': 's-instrument-0002',
            'description': 'Instrument master downloaded',
            'result': self.answers.get(segment, ''),
        }
        response = requests.Response()
        response.status_code = 200
        response.headers['Content-Type'] = 'application/json'
        response._content = self.encode(body)
        response.url = url
        return response

    def encode(self, body):
        """Encodes an answer body as JSON bytes.

        Args:
            body (dict): The answer body.

        Returns:
            bytes: The body as UTF-8 JSON.
        """
        return json.dumps(body).encode('utf-8')


class DownloadingEverySegmentExample:
    """Downloads the master from the canned answers and prints what came back.

    Attributes:
        session (RecordedMasterSession): The stand-in for Wisdom Capital's endpoint.
        instruments (WisdomCapitalInstruments): The ingester being shown.
    """

    def __init__(self):
        """Builds the stand-in session and the ingester.

        Returns:
            None: This method returns nothing.
        """
        self.session = RecordedMasterSession(SEGMENT_ANSWERS)
        self.instruments = WisdomCapitalInstruments()

    def run(self):
        """Downloads the master and prints the segments asked for and the rows returned.

        Returns:
            None: This method returns nothing.
        """
        with unittest.mock.patch.object(wisdom_capital_instruments, 'build_session', return_value=self.session):
            frame = self.instruments.download()
        print(f'Segments asked for: {self.session.segments_asked}')
        print(f'Rows: {len(frame)}')
        shown_columns = [
            'ExchangeSegment',
            'ExchangeInstrumentID',
            'InstrumentType',
            'Series',
            'LotSize',
            'StrikePrice',
            'ISIN',
            'data_category',
        ]
        print(frame[shown_columns].to_string())


if __name__ == '__main__':
    DownloadingEverySegmentExample().run()
