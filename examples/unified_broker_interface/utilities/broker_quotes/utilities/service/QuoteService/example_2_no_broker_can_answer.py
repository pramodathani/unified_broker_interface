"""Shows the quote service's answer when the cached quote is not good enough and no broker in service carries the instrument.

A cached quote marked stale is never served. The quote service then looks up the instrument's broker handles in the worker's mapping cache and asks those brokers whose REST quote module is in service. Fyers and Groww have quote modules that are not yet in service, so an instrument carried only by them has no broker to ask, and the answer is a `RequestError` with HTTP status 503. `quote` raises that error, while `quotes` returns it in the instrument's place, so one unanswerable instrument does not spoil the others in a batch.

The Redis client is a small stand-in class holding one stale quote for INFY and nothing for the second instrument. The mapping cache is a stand-in that says only Fyers and Groww carry INFY and nobody carries the second instrument. Because no broker in service is named, the service never builds a broker API client, so nothing leaves the process and no login happens.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/utilities/service/QuoteService/example_2_no_broker_can_answer.py
"""

import datetime
import json

from unified_broker_interface.utilities.broker_quotes.utilities.service import (
    QuoteService,
)
from unified_broker_interface.utilities.instrument_identity import (
    RequestError,
)

INFY = '22222222-2222-5222-8222-000000000001'
UNQUOTED = '22222222-2222-5222-8222-000000000005'


class QuoteCachePipeline:
    """A stand-in for a Redis pipeline that queues hash reads and answers them together.

    Attributes:
        hashes (dict): Hash keys to their fields and stored JSON values.
        commands (list): The (key, field) pairs queued.
    """

    def __init__(self, hashes):
        """Starts an empty pipeline.

        Args:
            hashes (dict): Hash keys to their fields and stored JSON values.

        Returns:
            None: This method returns nothing.
        """
        self.hashes = hashes
        self.commands = []

    def hget(self, key, field):
        """Queues a hash field read.

        Args:
            key (str): The hash key.
            field (str): The field.

        Returns:
            QuoteCachePipeline: This pipeline.
        """
        self.commands.append((key, field))
        return self

    def execute(self):
        """Answers every queued read.

        Returns:
            list: The stored value of each field, or None where it is absent.
        """
        replies = []
        for key, field in self.commands:
            replies.append(self.hashes.get(key, {}).get(field))
        return replies


class StaleQuoteRedis:
    """A stand-in for the Redis client holding one stale live quote for INFY.

    Attributes:
        hashes (dict): Hash keys to their fields and stored JSON values.
    """

    def __init__(self):
        """Holds INFY's stale live quote.

        Returns:
            None: This method returns nothing.
        """
        stale_quote = {
            'instrument_id': INFY,
            'last_price': 1512.35,
            'received_at': 1789446605.0,
            'stale': True,
        }
        self.hashes = {
            'unified:quotes:live': {
                INFY: json.dumps(stale_quote),
            },
        }

    def pipeline(self):
        """Starts a pipeline.

        Returns:
            QuoteCachePipeline: The pipeline.
        """
        return QuoteCachePipeline(self.hashes)


class NotInServiceMappingCache:
    """A stand-in for the worker's mapping cache in which only brokers not in service carry INFY."""

    def order_handles_for_instruments(self, instrument_identifiers, as_of_date, brokers=None):
        """Answers each instrument's broker handles.

        Args:
            instrument_identifiers (list): The instrument ids asked about.
            as_of_date (datetime.date): The mapping date.
            brokers (list | None): The brokers to restrict the answer to.

        Returns:
            dict: INFY's Fyers and Groww handles; the other instrument is absent.
        """
        return {
            INFY: {
                'fyers': {
                    'broker_token': '10100000001594',
                    'order_symbol': 'NSE:INFY-EQ',
                    'lot_size': '1',
                    'tick_size': '0.1',
                },
                'groww': {
                    'broker_token': '1594',
                    'order_symbol': 'INFY',
                    'lot_size': '1',
                    'tick_size': '0.1',
                },
            },
        }


class NoBrokerCanAnswerExample:
    """Asks for INFY alone and then for INFY with an unquoted instrument.

    Attributes:
        service (QuoteService): The quote service being shown.
    """

    def __init__(self):
        """Builds the service over the stand-ins.

        Returns:
            None: This method returns nothing.
        """
        self.service = QuoteService(NotInServiceMappingCache(), StaleQuoteRedis())

    def run(self):
        """Prints the error `quote` raises and the errors `quotes` returns.

        Returns:
            None: This method returns nothing.
        """
        mapping_date = datetime.date(2026, 9, 15)
        infy = {
            'instrument_id': INFY,
            'exchange': 'nse',
            'segment': 'nse_equities',
        }
        unquoted = {
            'instrument_id': UNQUOTED,
            'exchange': 'nse',
            'segment': 'nse_equities',
        }
        try:
            self.service.quote(infy, mapping_date)
        except RequestError as error:
            print(f'quote raised RequestError {error.status}: {error.message}')
        identities = [
            infy,
            unquoted,
        ]
        answers = self.service.quotes(identities, mapping_date)
        for identity, answer in zip(identities, answers):
            print(f'{identity["instrument_id"]}: {type(answer).__name__} {answer.status}: {answer.message}')


if __name__ == '__main__':
    NoBrokerCanAnswerExample().run()
