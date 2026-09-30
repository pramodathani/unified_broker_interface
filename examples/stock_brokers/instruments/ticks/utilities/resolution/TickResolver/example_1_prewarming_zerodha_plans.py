"""Compiles instrument plans for Zerodha's subscribed tokens before their first ticks arrive, and reads them back.

`TickResolver` turns the token on a tick into an `InstrumentPlan`. The live service calls `prewarm` with the broker's whole subscription set when it starts, so the mapping search happens once, off the per-tick path; after that `plan_for` is a single dictionary look-up. Plans are filed under the tick's spelling, which for Kite is an integer, while the subscription set holds strings.

Compiling a plan decides the instrument's lot size from every broker's order handle. On MCX the authority is Groww's lot, the only one that makes price times quantity the contract's value; elsewhere the most common lot wins, and a disagreement is kept in `notes` and logged once. This program gives the resolver a stand-in mapping cache with three Zerodha instruments and a stand-in logger that prints, so it needs no data store. The brokers' disagreement over the NIFTY future's lot is invented for the demonstration. The clock is fixed at 09:30 India time on 2026-09-15.

The subscription set also holds `NSE:INFY`, which is not a Kite token, so it is recorded as unplaceable. That miss is recorded before the resolver has first read its mapping date, so the first `refresh` counts it as a plan to drop and logs that plans will be recompiled, although none had been compiled yet.

Run it from the project root:

    python examples/stock_brokers/instruments/ticks/utilities/resolution/TickResolver/example_1_prewarming_zerodha_plans.py
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


class StandInMappingCache:
    """A stand-in for `MappingCache` holding three Zerodha instruments for 2026-09-15.

    Attributes:
        mapping_date (datetime.date): The one mapping date this cache holds.
        identities (dict): Zerodha token to the identities it maps to.
        handles (dict): Instrument id to broker name to order handle.
        engine (None): The real cache's database engine, which this program never uses.
    """

    def __init__(self):
        """Fills the cache.

        Returns:
            None: This method returns nothing.
        """
        self.mapping_date = datetime.date(2026, 9, 15)
        self.engine = None
        self.identities = {
            '738561': [
                self.identity('102', 'nse', 'nse_equities', 'security', 'RELIANCE', None, None),
            ],
            '5720583': [
                self.identity('101', 'mcx', 'mcx_commodity_futures', 'future', 'CRUDEOIL26OCTFUT', 'CRUDEOIL', '2026-10-19'),
            ],
            '13238786': [
                self.identity('105', 'nse', 'nse_equity_index_futures', 'future', 'NIFTY26SEPFUT', 'NIFTY', '2026-09-29'),
            ],
        }
        self.handles = {
            self.instrument_id('102'): {
                'zerodha': self.handle('738561', '1'),
                'dhan': self.handle('2885', '1'),
            },
            self.instrument_id('101'): {
                'zerodha': self.handle('5720583', '100'),
                'kotak': self.handle('440001', '1'),
                'groww': self.handle('440001', '100'),
            },
            self.instrument_id('105'): {
                'zerodha': self.handle('13238786', '75'),
                'dhan': self.handle('35003', '75'),
                'kotak': self.handle('35003', '65'),
            },
        }

    def instrument_id(self, suffix):
        """Builds an instrument id.

        Args:
            suffix (str): The last digits of the id.

        Returns:
            str: The id.
        """
        return f'11111111-1111-5111-8111-000000000{suffix}'

    def identity(self, suffix, exchange, segment, shape, symbol, underlying_symbol, expiry_date):
        """Builds one identity as the real cache returns it.

        Args:
            suffix (str): The last digits of the instrument id.
            exchange (str): The canonical exchange.
            segment (str): The canonical segment.
            shape (str): "security", "future" or "option".
            symbol (str): The trading symbol.
            underlying_symbol (str | None): The underlying, for a derivative.
            expiry_date (str | None): The expiry, for a derivative.

        Returns:
            dict: The identity.
        """
        return {
            'instrument_id': self.instrument_id(suffix),
            'exchange': exchange,
            'segment': segment,
            'shape': shape,
            'symbol': symbol,
            'underlying_symbol': underlying_symbol,
            'expiry_date': expiry_date,
            'strike_price': None,
            'option_type': None,
        }

    def handle(self, broker_token, lot_size):
        """Builds one broker's order handle.

        Args:
            broker_token (str): The broker's token.
            lot_size (str): The broker's lot size.

        Returns:
            dict: The handle.
        """
        return {
            'broker_token': broker_token,
            'order_symbol': None,
            'lot_size': lot_size,
            'tick_size': '0.05',
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
            for identity in self.identities.get(token, []):
                if segments is None or identity['segment'] in segments:
                    matches.append(identity)
            if matches:
                found[token] = matches
        return found

    def order_handles_for_instruments(self, instrument_identifiers, as_of_date, brokers=None):
        """Answers every broker's order handle for each instrument.

        Args:
            instrument_identifiers (list): The instrument ids.
            as_of_date (datetime.date): The trading day.
            brokers (list | None): Brokers to restrict the answer to, or None for all.

        Returns:
            dict: Instrument id to broker name to handle.
        """
        found = {}
        for instrument_id in instrument_identifiers:
            if instrument_id in self.handles:
                found[instrument_id] = self.handles[instrument_id]
        return found


class PrewarmingZerodhaPlansExample:
    """Prewarms Zerodha's subscription set and prints the compiled plans.

    Attributes:
        resolver (TickResolver): The resolver being shown.
        now (float): The fixed current instant, in epoch seconds.
    """

    def __init__(self):
        """Builds the resolver over the stand-in cache with Zerodha's normalizer.

        Returns:
            None: This method returns nothing.
        """
        source = CacheCandidateSource(StandInMappingCache())
        brokers = [
            'zerodha',
        ]
        self.resolver = TickResolver(source, build_normalizers(brokers), PrintingLogger())
        moment = datetime.datetime(2026, 9, 15, 9, 30, tzinfo=INDIA)
        self.now = moment.timestamp()

    def run(self):
        """Prewarms, looks one plan up, and prints every plan and note.

        Returns:
            None: This method returns nothing.
        """
        subscriptions = [
            '738561',
            '5720583',
            '13238786',
            'NSE:INFY',
        ]
        planned, total = self.resolver.prewarm('zerodha', subscriptions, self.now)
        print(f'Prewarmed {planned} of {total} subscribed tokens')
        print(f'As of {self.resolver.as_of_date}, from mapping date {self.resolver.mapping_date}')
        plan = self.resolver.plan_for('zerodha', 738561, self.now)
        print(f'plan_for 738561: {plan.instrument_id} {plan.segment}, session closes trading at {plan.session.trading_close} seconds')
        for key, compiled in self.resolver.plans().items():
            broker_name, token = key
            print(f"{broker_name} {token!r}: {compiled.shape} on {compiled.exchange}, lot {compiled.lot_size}, volume multiplier {compiled.multipliers['volume']}, close policy {compiled.close_policy}")
        print(f'Notes: {self.resolver.notes}')
        print(f'Unresolved: {dict(self.resolver.drain_unresolved())}')


if __name__ == '__main__':
    PrewarmingZerodhaPlansExample().run()
