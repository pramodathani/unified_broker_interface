"""Classifies Stoxkart rows through the checks that run before and after its rules, and shows its uneven scales.

Stoxkart lists some instruments more than once, marks calendar spreads with the same instrument type as real contracts, and scales strikes and ticks differently across its own segments. `StoxkartMappingAdapter.classify` therefore runs code checks first (winner tokens, other brokers' fund lists, spread patterns), then the rules, then filters on the rules' answer (a fund ISIN makes an NSE equity an exchange traded fund, an "SP-" description marks an NSE spread, a row with no ISIN is an index), and finally fallbacks for segments that have no rules.

`to_identity` names NSE indices from the description and brings them to the spelling shared with other brokers, and stores bonds under their ISIN. `to_broker_fields` drops the tick size that Stoxkart puts on every index row whatever the real tick, and the rules divide strikes by 100. `run` normally computes the winner tokens from the whole day's file and gathers the fund list and index lookup from the database; this program sets them by hand, so no database is needed. `uncategorised_exchange` shows where a dropped row is filed.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/stoxkart/StoxkartMappingAdapter/example_1_checks_around_the_rules.py
"""

from stock_brokers.instruments.mapping.stoxkart import (
    StoxkartMappingAdapter,
)


class ChecksAroundTheRulesExample:
    """Classifies eight hand-written Stoxkart rows and prints each one's segment, identity and sizes.

    Attributes:
        adapter (StoxkartMappingAdapter): The adapter being shown.
        raw_rows (list): The raw rows, as dictionaries of text columns.
    """

    def __init__(self):
        """Builds the adapter, sets the sets `run` would compute, and writes the rows.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = StoxkartMappingAdapter()
        self.adapter.bse_etf_symbols = set()
        self.adapter.nse_index_master_lookup = {}
        self.adapter.nse_equities_winning_tokens = {
            '2885',
        }
        self.adapter.bse_equities_winning_tokens = set()
        self.adapter.bse_fixed_income_winning_tokens = {
            '950001',
        }
        self.adapter.mcx_options_winning_tokens = set()
        self.raw_rows = [
            self.raw_row('NSE', '2885', 'RELIANCE', 'RELIANCE INDUSTRIES LTD', 'EQ', None, 'INE002A01018', None, None, None),
            self.raw_row('NSE', '10576', 'NIFTYBEES', 'NIPPON INDIA ETF NIFTY 50 BEES', 'EQ', None, 'INF204KB14I2', None, None, None),
            self.raw_row('NSE', '26009', 'Nifty Bank', 'Nifty Bank', 'EQ', None, None, None, None, None),
            self.raw_row('BSE', '950001', '762GS2036', 'GOI 7.62% 2036', 'G', None, 'IN0020160019', None, None, None),
            self.raw_row('NFO', '52168', 'NIFTY', 'NIFTY26OCTFUT', None, 'FUTIDX', None, '27-10-2026', None, None),
            self.raw_row('NFO', '99001', 'NIFTY', 'SP-NIFTY26OCT26NOVFUT', None, 'FUTIDX', None, '27-10-2026', None, None),
            self.raw_row('NFO', '40215', 'NIFTY', 'NIFTY26OCT25000CE', None, 'OPTIDX', None, '27-10-2026', '2500000', 'CE'),
            self.raw_row('NCDEX', '71003', 'GUARSEED10', 'GUARSEED10NOVDEC2026', None, 'FUTCOM', None, '20-11-2026', None, None),
        ]

    def raw_row(self, exchange, token, symbol, description, series, instrument_type, isin, expiry, strike, option_type):
        """Builds one raw row in the shape of `stoxkart.instruments`.

        Args:
            exchange (str): The exchange code, such as NSE, NFO, BSE or NCDEX.
            token (str): Stoxkart's token for the row.
            symbol (str): The `symbol` column.
            description (str): The `symbol_description` column.
            series (str | None): The exchange series, for cash rows.
            instrument_type (str | None): The instrument type, for derivatives.
            isin (str | None): The `isin_code` column.
            expiry (str | None): The expiry as `DD-MM-YYYY` text.
            strike (str | None): The strike in hundredths of a rupee.
            option_type (str | None): CE or PE for an option.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        return {
            'exchange': exchange,
            'token': token,
            'symbol': symbol,
            'symbol_description': description,
            'series': series,
            'instrument_type': instrument_type,
            'option_type': option_type,
            'expiry_date': expiry,
            'lot_size': '1',
            'strike_price': strike,
            'isin_code': isin,
            'tick_size': '5',
        }

    def run(self):
        """Prints each row's segment, identity and sizes, or where an unmatched row is filed.

        Returns:
            None: This method returns nothing.
        """
        for raw_row in self.raw_rows:
            label = f'{raw_row["exchange"]} {raw_row["symbol_description"]}'
            segment_configuration = self.adapter.classify(raw_row)
            if segment_configuration is None:
                exchange = self.adapter.uncategorised_exchange(raw_row)
                print(f'{label} -> no segment, filed under {exchange}_uncategorised')
                continue
            identity = self.adapter.to_identity(raw_row, segment_configuration)
            broker_fields = self.adapter.to_broker_fields(raw_row, segment_configuration)
            print(f'{label} -> {segment_configuration["segment"]}')
            print(f'    identity {identity}')
            print(f'    lot size {broker_fields["lot_size"]}, tick size {broker_fields["tick_size"]}')


if __name__ == '__main__':
    ChecksAroundTheRulesExample().run()
