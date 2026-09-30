"""Classifies Groww rows that need redirects, exclusions and symbol clean-up on top of the rules.

Groww puts stock and index derivatives in one FNO segment with nothing to tell them apart, lists exchange traded funds under its plain equity series, and has no series or tag of its own for NSE bonds. `GrowwMappingAdapter.classify` therefore files an NSE cash row as fixed income when its series is none of the known equity, fund or trust series and it has a non-fund ISIN, moves NSE equity rows with a fund ISIN to exchange traded funds, moves derivatives on NIFTY or on the MCX commodity indices to the index segments, and drops BSE series B rows that carry a fund ISIN.

`to_identity` brings index names to one spelling (Groww's `NIFTYJR` is stored as NIFTYNXT50) and strips Groww's `-MF`, `-IV` and `-EQ` suffixes from fund and trust symbols. `to_broker_fields` falls back to the trading symbol when a BSE bond has no name. `run` normally gathers the BSE exchange traded fund list and the index name lookup from the database; this program sets both to empty by hand, so no database is needed. `uncategorised_exchange` shows where a dropped row is filed.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/groww/GrowwMappingAdapter/example_1_redirects_and_suffixes.py
"""

from stock_brokers.instruments.mapping.groww import (
    GrowwMappingAdapter,
)


class RedirectsAndSuffixesExample:
    """Classifies eight hand-written Groww rows and prints each one's segment, identity and broker fields.

    Attributes:
        adapter (GrowwMappingAdapter): The adapter being shown.
        raw_rows (list): The raw rows, as dictionaries of text columns.
    """

    def __init__(self):
        """Builds the adapter, sets the lists `run` would gather, and writes the rows.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = GrowwMappingAdapter()
        self.adapter.bse_etf_symbols = set()
        self.adapter.nse_index_master_lookup = {}
        self.raw_rows = [
            self.raw_row('NSE', 'CASH', 'EQ', 'EQ', '10576', 'NIFTYBEES', 'Nippon India ETF Nifty 50 BeES', 'INF204KB14I2', None, None),
            self.raw_row('NSE', 'CASH', 'EQ', 'GS', '15542', '762GS2036', None, 'IN0020160019', None, None),
            self.raw_row('NSE', 'CASH', 'EQ', 'MF', '20105', 'HDFCNIFTY-MF', 'HDFC Nifty 50 Index Fund', 'INF179KB1HP9', None, None),
            self.raw_row('NSE', 'CASH', 'IDX', None, 'NIFTY JR', 'NIFTYJR', 'NIFTY NEXT 50', None, None, None),
            self.raw_row('NSE', 'FNO', 'FUT', None, '52168', 'NIFTY26OCTFUT', None, None, 'NIFTY', '2026-10-27'),
            self.raw_row('MCX', 'COMMODITY', 'FUT', None, '466583', 'MCXBULLDEX26OCTFUT', None, None, 'MCXBULLDEX', '2026-10-28'),
            self.raw_row('BSE', 'CASH', 'EQ', 'F', '973412', '800IIFL28', None, 'INE530B07393', None, None),
            self.raw_row('BSE', 'CASH', 'EQ', 'B', '590154', 'LICMFGOLD', 'LIC MF Gold ETF', 'INF767K01RW0', None, None),
        ]

    def raw_row(self, exchange, segment, instrument_type, series, token, trading_symbol, name, isin, underlying_symbol, expiry):
        """Builds one raw row in the shape of `groww.instruments`.

        Args:
            exchange (str): The exchange, as NSE, BSE or MCX.
            segment (str): Groww's segment, as CASH, FNO or COMMODITY.
            instrument_type (str): Groww's instrument type.
            series (str | None): The exchange series, for cash rows.
            token (str): The `exchange_token` column.
            trading_symbol (str): The `trading_symbol` column.
            name (str | None): The readable name, which Groww leaves blank on some rows.
            isin (str | None): The ISIN, if Groww published one.
            underlying_symbol (str | None): The underlying, for derivatives.
            expiry (str | None): The expiry date as text, for derivatives.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        return {
            'exchange': exchange,
            'exchange_token': token,
            'trading_symbol': trading_symbol,
            'name': name,
            'instrument_type': instrument_type,
            'segment': segment,
            'series': series,
            'isin': isin,
            'underlying_symbol': underlying_symbol,
            'expiry_date': expiry,
            'strike_price': None,
            'lot_size': '1',
            'tick_size': '0.01',
        }

    def run(self):
        """Prints each row's segment, identity and broker symbol, or where an unmatched row is filed.

        Returns:
            None: This method returns nothing.
        """
        for raw_row in self.raw_rows:
            label = f'{raw_row["exchange"]} {raw_row["trading_symbol"]} ({raw_row["instrument_type"]}, series {raw_row["series"]})'
            segment_configuration = self.adapter.classify(raw_row)
            if segment_configuration is None:
                exchange = self.adapter.uncategorised_exchange(raw_row)
                print(f'{label} -> no segment, filed under {exchange}_uncategorised')
                continue
            identity = self.adapter.to_identity(raw_row, segment_configuration)
            broker_fields = self.adapter.to_broker_fields(raw_row, segment_configuration)
            print(f'{label} -> {segment_configuration["segment"]}')
            print(f'    identity {identity}, broker symbol {broker_fields["broker_symbol"]!r}')


if __name__ == '__main__':
    RedirectsAndSuffixesExample().run()
