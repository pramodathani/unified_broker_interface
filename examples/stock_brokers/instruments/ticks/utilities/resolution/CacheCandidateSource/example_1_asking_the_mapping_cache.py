"""Asks the mapping cache, through `CacheCandidateSource`, which instruments a broker's tokens can be and what every broker calls them.

`TickResolver` never searches the mappings itself. It asks a candidate source three questions: which mapping date answers for a trading day, every identity a list of broker tokens maps to inside some segments, and every broker's order handle for some instruments. `CacheCandidateSource` answers them from the process's three-tier `MappingCache`, which in the live service is backed by Redis and TimescaleDB.

This program gives it a small stand-in cache holding two Zerodha tokens for 2026-09-15, so it runs without any data store. The stand-in answers the same three calls the real `MappingCache` does, with the same shapes, and refuses a day before its mapping date by answering None, which is how the real cache tells the resolver to look elsewhere. Notice that the segment filter matters: token 738561 is searched only among the segments the caller names.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/utilities/resolution/CacheCandidateSource/example_1_asking_the_mapping_cache.py
"""

import datetime

from stock_brokers.instruments.ticks.utilities.resolution import (
    CacheCandidateSource,
)


class StandInMappingCache:
    """A stand-in for `MappingCache` that holds a few identities and handles in memory.

    Attributes:
        mapping_date (datetime.date): The one mapping date this cache holds.
        identities (dict): (broker, token) to the list of identities the token maps to.
        handles (dict): Instrument id to broker name to that broker's order handle.
        engine (None): The real cache's database engine, which this program never uses.
    """

    def __init__(self):
        """Fills the cache with RELIANCE on NSE and a crude oil future on MCX.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 15)
        self.engine = None
        reliance = {
            'instrument_id': '11111111-1111-5111-8111-000000000102',
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
            'symbol': 'RELIANCE',
            'underlying_symbol': None,
            'expiry_date': None,
            'strike_price': None,
            'option_type': None,
        }
        crude_oil = {
            'instrument_id': '11111111-1111-5111-8111-000000000101',
            'exchange': 'mcx',
            'segment': 'mcx_commodity_futures',
            'shape': 'future',
            'symbol': 'CRUDEOIL26OCTFUT',
            'underlying_symbol': 'CRUDEOIL',
            'expiry_date': datetime.date(2026, 10, 19),
            'strike_price': None,
            'option_type': None,
        }
        self.identities = {
            ('zerodha', '738561'): [
                reliance,
            ],
            ('zerodha', '5720583'): [
                crude_oil,
            ],
        }
        self.handles = {
            reliance['instrument_id']: {
                'zerodha': {
                    'broker_token': '738561',
                    'order_symbol': 'RELIANCE',
                    'lot_size': '1',
                    'tick_size': '0.1',
                },
                'dhan': {
                    'broker_token': '2885',
                    'order_symbol': 'RELIANCE',
                    'lot_size': '1',
                    'tick_size': '0.1',
                },
            },
        }

    def resolves_to_current_date(self, as_of_date):
        """Answers the mapping date for a day, or None for a day before it.

        Args:
            as_of_date (datetime.date): The trading day asked about.

        Returns:
            datetime.date | None: The mapping date, or None.
        """
        if as_of_date < self.mapping_date:
            return None
        return self.mapping_date

    def candidates_for_tokens(self, broker, broker_tokens, as_of_date, segments=None):
        """Answers every identity each token maps to inside the segments.

        Args:
            broker (str): The broker name.
            broker_tokens (list): The broker's tokens.
            as_of_date (datetime.date): The trading day.
            segments (list | None): The segments to search, or None for any.

        Returns:
            dict: Token to a list of identities; tokens with none are absent.
        """
        found = {}
        for token in broker_tokens:
            matches = []
            for identity in self.identities.get((broker, str(token)), []):
                if segments is None or identity['segment'] in segments:
                    matches.append(identity)
            if matches:
                found[str(token)] = matches
        return found

    def order_handles_for_instruments(self, instrument_identifiers, as_of_date, brokers=None):
        """Answers every broker's order handle for each instrument.

        Args:
            instrument_identifiers (list): The instrument ids.
            as_of_date (datetime.date): The trading day.
            brokers (list | None): Brokers to restrict the answer to, or None for all.

        Returns:
            dict: Instrument id to broker name to handle; instruments with none are absent.
        """
        found = {}
        for instrument_id in instrument_identifiers:
            if instrument_id in self.handles:
                found[instrument_id] = self.handles[instrument_id]
        return found


class AskingTheMappingCacheExample:
    """Asks a candidate source the resolver's three questions and prints the answers.

    Attributes:
        source (CacheCandidateSource): The source being shown.
    """

    def __init__(self):
        """Wraps the stand-in mapping cache in a candidate source.

        Returns:
            None: This method returns nothing.
        """
        self.source = CacheCandidateSource(StandInMappingCache())

    def run(self):
        """Prints the mapping date, candidates and handles.

        Returns:
            None: This method returns nothing.
        """
        today = datetime.date(2026, 9, 15)
        last_week = datetime.date(2026, 9, 8)
        print(f'Mapping date for {today}: {self.source.mapping_date(today)}')
        print(f'Mapping date for {last_week}: {self.source.mapping_date(last_week)}')
        tokens = [
            '738561',
            '5720583',
            '999',
        ]
        cash_segments = (
            'nse_equities',
            'nse_exchange_traded_funds',
        )
        found = self.source.candidates('zerodha', tokens, today, cash_segments)
        print(f'Tokens {tokens} among NSE cash segments:')
        for token, identities in found.items():
            for identity in identities:
                print(f"  {token} -> {identity['symbol']} ({identity['segment']}) {identity['instrument_id']}")
        commodity_segments = (
            'mcx_commodity_futures',
        )
        found = self.source.candidates('zerodha', tokens, today, commodity_segments)
        print(f'The same tokens among MCX commodity futures: {sorted(found)}')
        instrument_ids = [
            '11111111-1111-5111-8111-000000000102',
        ]
        handles = self.source.handles(instrument_ids, today)
        for instrument_id, by_broker in handles.items():
            for broker_name, handle in by_broker.items():
                print(f"Handle for {instrument_id} at {broker_name}: token {handle['broker_token']}, lot {handle['lot_size']}, tick {handle['tick_size']}")


if __name__ == '__main__':
    AskingTheMappingCacheExample().run()
