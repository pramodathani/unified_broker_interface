"""Classifies Fyers rows, whose exchange, segment and instrument type are numeric codes, and reads symbols out of tickers.

Fyers writes NSE as exchange 10, MCX as 11 and BSE as 12, and the cash market as segment 10, derivatives as 11 and currency as 12. `FyersMappingAdapter.classify` routes the NSE and BSE cash markets in code, because one instrument type code covers several segments: a BSE type 50 row is an equity or a bond depending on the suffix of its ticker and on its ISIN, and an NSE type 0 row is an investment trust when other brokers say so. It also moves the ONMIBOR rate futures to the fixed income index futures segment, and drops the bond-shaped "NIFTYGS" index rows.

`to_identity` reads the symbol out of a ticker such as `NSE:RELIANCE-EQ` where the rules name the ticker as the source, and brings index names to the spelling shared with other brokers. `run` normally gathers the investment trust and exchange traded fund lists and the index name lookup from the database; this program sets them by hand, so no database is needed. `uncategorised_exchange` turns the numeric exchange code of a dropped row into an exchange name.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/fyers/FyersMappingAdapter/example_1_numeric_codes_and_tickers.py
"""

from stock_brokers.instruments.mapping.fyers import (
    FyersMappingAdapter,
)


class NumericCodesAndTickersExample:
    """Classifies eight hand-written Fyers rows and prints each one's segment and identity.

    Attributes:
        adapter (FyersMappingAdapter): The adapter being shown.
        raw_rows (list): The raw rows, as dictionaries of text columns.
    """

    def __init__(self):
        """Builds the adapter, sets the lists `run` would gather, and writes the rows.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = FyersMappingAdapter()
        self.adapter.nse_investment_trust_symbols = {
            'EMBASSY',
        }
        self.adapter.bse_investment_trust_symbols = set()
        self.adapter.bse_etf_symbols = set()
        self.adapter.nse_index_master_lookup = {}
        self.raw_rows = [
            self.raw_row('10', '10', '0', 'NSE:RELIANCE-EQ', 'RELIANCE', 'INE002A01018', None),
            self.raw_row('10', '10', '0', 'NSE:EMBASSY-RR', 'EMBASSY', 'INE041025011', None),
            self.raw_row('10', '10', '10', 'NSE:NIFTYBANK-INDEX', 'NIFTYBANK', None, None),
            self.raw_row('10', '10', '10', 'NSE:NIFTYGS10YR-INDEX', 'NIFTYGS10YR', None, None),
            self.raw_row('12', '10', '50', 'BSE:737GS2028-F', '737GS2028', 'IN0020230010', None),
            self.raw_row('12', '10', '10', 'BSE:SENSEX50-INDEX', 'SENSEX50', None, None),
            self.raw_row('10', '12', '18', 'NSE:ONMIBOR26OCTFUT', 'ONMIBOR', None, '1793354400'),
            self.raw_row('11', '20', '99', 'MCX:GOLDGUINEA26OCTSPD', 'GOLDGUINEA', None, None),
        ]

    def raw_row(self, exchange, segment, instrument_type, ticker, underlying_symbol, isin, expiry):
        """Builds one raw row in the shape of `fyers.instruments`.

        Args:
            exchange (str): Fyers' numeric exchange code.
            segment (str): Fyers' numeric segment code.
            instrument_type (str): Fyers' numeric instrument type code.
            ticker (str): The `symbol_ticker` column.
            underlying_symbol (str): The `underlying_symbol` column.
            isin (str | None): The ISIN, if Fyers published one.
            expiry (str | None): The expiry as seconds since 1970, for a derivative.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        return {
            'symbol_details': ticker.split(':')[1],
            'exchange_instrument_type': instrument_type,
            'minimum_lot_size': '1',
            'tick_size': '0.05',
            'isin': isin,
            'expiry_date': expiry,
            'symbol_ticker': ticker,
            'exchange': exchange,
            'segment': segment,
            'underlying_symbol': underlying_symbol,
            'strike_price': None,
            'option_type': None,
        }

    def run(self):
        """Prints the segment and identity of each row, or where an unmatched row is filed.

        Returns:
            None: This method returns nothing.
        """
        for raw_row in self.raw_rows:
            label = f'{raw_row["symbol_ticker"]} (type {raw_row["exchange_instrument_type"]})'
            segment_configuration = self.adapter.classify(raw_row)
            if segment_configuration is None:
                exchange = self.adapter.uncategorised_exchange(raw_row)
                print(f'{label} -> no segment, filed under {exchange}_uncategorised')
                continue
            identity = self.adapter.to_identity(raw_row, segment_configuration)
            print(f'{label} -> {segment_configuration["segment"]}')
            print(f'    identity {identity}')


if __name__ == '__main__':
    NumericCodesAndTickersExample().run()
