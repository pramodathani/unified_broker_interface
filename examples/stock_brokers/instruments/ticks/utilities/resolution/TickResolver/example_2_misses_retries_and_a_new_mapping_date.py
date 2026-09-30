"""Shows how `TickResolver` refuses to guess, how long it leaves a miss alone, and what a new mapping date does to its plans.

A token that does not resolve to exactly one live instrument gets no plan. The resolver records why: `unplaceable` when the broker's normalizer cannot read the token, `unmapped` when nothing in the mappings matches it (an expired contract counts as no match), `ambiguous` when it matches more than one instrument, and `no_normalizer` for a broker it has no normalizer for. Writing one instrument's prices under another's id would be worse than writing nothing, so an ambiguous token is never resolved to its first candidate.

A miss is remembered for ten minutes, so a token nothing maps costs one search per ten minutes rather than one per tick. `drain_unresolved` hands the counts to whoever reports them and starts again. `refresh` is called every thirty seconds by the live service; when the mapping date moves, after the morning's download, it drops every plan so they are compiled again from the new mappings.

The stand-in mapping cache counts every search it answers, which shows when the resolver asks again. A stand-in logger prints each warning, and the clock is passed in, fixed at 09:30 India time on 2026-09-15. No data store is involved.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/utilities/resolution/TickResolver/example_2_misses_retries_and_a_new_mapping_date.py
"""

import datetime
import zoneinfo

from stock_brokers.instruments.ticks.utilities.registry import (
    build_normalizers,
)
from stock_brokers.instruments.ticks.utilities.resolution import (
    CacheCandidateSource,
    TickResolver,
)

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')


class PrintingLogger:
    """A stand-in logger that prints each message with its level."""

    def info(self, message):
        """Prints an informational message.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'LOG info: {message}')

    def warning(self, message):
        """Prints a warning.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'LOG warning: {message}')


class CountingMappingCache:
    """A stand-in for `MappingCache` that counts the searches it answers.

    Attributes:
        mapping_date (datetime.date): The mapping date the cache holds, which the program moves.
        searches (int): How many candidate searches have been answered.
        identities (dict): Zerodha token to the identities it maps to.
        engine (None): The real cache's database engine, which this program never uses.
    """

    def __init__(self):
        """Fills the cache with one good token, one ambiguous token and one expired contract.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 15)
        self.searches = 0
        self.engine = None
        self.identities = {
            '738561': [
                self.identity('102', 'RELIANCE', None),
            ],
            '408065': [
                self.identity('107', 'INFY', None),
                self.identity('108', 'INFY-BE', None),
            ],
            '13238786': [
                self.identity('109', 'NIFTY26AUGFUT', '2026-08-27'),
            ],
        }

    def identity(self, suffix, symbol, expiry_date):
        """Builds one identity as the real cache returns it.

        Args:
            suffix (str): The last digits of the instrument id.
            symbol (str): The trading symbol.
            expiry_date (str | None): The expiry, for a derivative.

        Returns:
            dict: The identity.
        """
        segment = 'nse_equities'
        shape = 'security'
        if expiry_date is not None:
            segment = 'nse_equity_index_futures'
            shape = 'future'
        return {
            'instrument_id': f'11111111-1111-5111-8111-000000000{suffix}',
            'exchange': 'nse',
            'segment': segment,
            'shape': shape,
            'symbol': symbol,
            'underlying_symbol': None,
            'expiry_date': expiry_date,
            'strike_price': None,
            'option_type': None,
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
        """Answers every identity each token maps to inside the segments, and counts the search.

        Args:
            broker (str): The broker name.
            broker_tokens (list): The broker's tokens.
            as_of_date (datetime.date): The trading day.
            segments (list | None): The segments to search, or None for any.

        Returns:
            dict: Token to a list of identities; tokens with none are absent.
        """
        self.searches += 1
        found = {}
        for token in broker_tokens:
            matches = []
            for identity in self.identities.get(token, []):
                if segments is None or identity['segment'] in segments:
                    matches.append(identity)
            if matches:
                found[token] = matches
        return found

    def order_handles_for_instruments(self, instrument_identifiers, as_of_date, brokers=None):
        """Answers each instrument's handles, which here are only Zerodha's lot of 1.

        Args:
            instrument_identifiers (list): The instrument ids.
            as_of_date (datetime.date): The trading day.
            brokers (list | None): Brokers to restrict the answer to, or None for all.

        Returns:
            dict: Instrument id to broker name to handle.
        """
        found = {}
        for instrument_id in instrument_identifiers:
            found[instrument_id] = {
                'zerodha': {
                    'broker_token': None,
                    'order_symbol': None,
                    'lot_size': '1',
                    'tick_size': '0.05',
                },
            }
        return found


class MissesAndRetriesExample:
    """Resolves tokens that miss, retries them, and moves the mapping date.

    Attributes:
        cache (CountingMappingCache): The stand-in mapping cache.
        resolver (TickResolver): The resolver being shown.
        now (float): The fixed current instant, in epoch seconds.
    """

    def __init__(self):
        """Builds the resolver with Zerodha's normalizer only.

        Returns:
            None: This method returns nothing.
        """
        self.cache = CountingMappingCache()
        brokers = [
            'zerodha',
        ]
        self.resolver = TickResolver(CacheCandidateSource(self.cache), build_normalizers(brokers), PrintingLogger())
        moment = datetime.datetime(2026, 9, 15, 9, 30, tzinfo=INDIA)
        self.now = moment.timestamp()

    def run(self):
        """Prints each step's outcome.

        Returns:
            None: This method returns nothing.
        """
        self.resolver.refresh(self.now)
        tokens = [
            738561,
            408065,
            13238786,
            1025,
            'NSE:INFY',
        ]
        compiled = self.resolver.compile('zerodha', tokens, self.now)
        print(f'Compiled: {sorted(compiled)}')
        print(f'Searches so far: {self.cache.searches}')
        print(f"plan_for upstox 42: {self.resolver.plan_for('upstox', 42, self.now)}")
        five_minutes_later = self.now + 300
        print(f"plan_for 408065 five minutes later: {self.resolver.plan_for('zerodha', 408065, five_minutes_later)}, searches {self.cache.searches}")
        eleven_minutes_later = self.now + 660
        print(f"plan_for 408065 eleven minutes later: {self.resolver.plan_for('zerodha', 408065, eleven_minutes_later)}, searches {self.cache.searches}")
        drained = self.resolver.drain_unresolved()
        for key in sorted(drained, key=str):
            print(f'Unresolved {key}: {drained[key]}')
        print(f'Unresolved after draining: {dict(self.resolver.unresolved)}')
        print(f'refresh later the same day: {self.resolver.refresh(self.now + 3600)}')
        self.cache.mapping_date = datetime.date(2026, 9, 16)
        next_morning = datetime.datetime(2026, 9, 16, 8, 0, tzinfo=INDIA)
        print(f'refresh after the next mapping date: {self.resolver.refresh(next_morning.timestamp())}')
        print(f'Plans left: {self.resolver.plans()}, mapping date {self.resolver.mapping_date}')


if __name__ == '__main__':
    MissesAndRetriesExample().run()
