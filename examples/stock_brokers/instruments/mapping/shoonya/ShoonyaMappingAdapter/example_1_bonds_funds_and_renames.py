"""Classifies Shoonya rows, which carry no ISIN and a stale symbol column on BSE derivatives.

Shoonya's file has no ISIN column, so `ShoonyaMappingAdapter.classify` files an NSE or BSE bond only when its token appears in a map from exchange token to ISIN built out of other brokers' files, and `to_identity` stores the bond under that ISIN. A bond whose token the map does not know is left uncategorised rather than stored under a name no other broker would match. Exchange traded funds share instrument codes with plain equities, so they are decided by symbol lists from other brokers, and every BSE row in Shoonya's group E is a fund.

On BSE derivatives, Shoonya's `symbol` column keeps a company's old name after a rename, so `to_identity` reads the underlying from the trading symbol instead: the row below, still labelled ZOMATO, is stored under ETERNAL. NSE index names are brought to the spelling shared with other brokers.

`run` normally builds the lists, the token map and the index name lookup from the database. This program sets them by hand, so no database is needed. `uncategorised_exchange` shows where a dropped row is filed, including Shoonya's NCDEX rows.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/shoonya/ShoonyaMappingAdapter/example_1_bonds_funds_and_renames.py
"""

from stock_brokers.instruments.mapping.shoonya import (
    ShoonyaMappingAdapter,
)


class BondsFundsAndRenamesExample:
    """Classifies eight hand-written Shoonya rows and prints each one's segment and identity.

    Attributes:
        adapter (ShoonyaMappingAdapter): The adapter being shown.
        raw_rows (list): The raw rows, as dictionaries of text columns.
    """

    def __init__(self):
        """Builds the adapter, sets the lists and maps `run` would build, and writes the rows.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = ShoonyaMappingAdapter()
        self.adapter.nse_etf_symbols = {
            'NIFTYBEES',
        }
        self.adapter.bse_etf_symbols = set()
        self.adapter.nse_fund_symbols = set()
        self.adapter.bse_fund_symbols = set()
        self.adapter.isin_by_token = {
            '15542': 'IN0020160019',
        }
        self.adapter.nse_index_master_lookup = {}
        self.raw_rows = [
            self.raw_row('NSE', '2885', 'RELIANCE', 'RELIANCE-EQ', 'EQ', None),
            self.raw_row('NSE', '10576', 'NIFTYBEES', 'NIFTYBEES-EQ', 'EQ', None),
            self.raw_row('NSE', '15542', '762GS2036', '762GS2036-GS', 'GS', None),
            self.raw_row('NSE', '19011', '845NCD29', '845NCD29-N1', 'N1', None),
            self.raw_row('BSE', '590095', 'GOLDBEES', 'GOLDBEES', 'E', None),
            self.raw_row('BFO', '1143520', 'ZOMATO', 'ETERNAL26OCTFUT', 'FUTSTK', '27-OCT-2026'),
            self.raw_row('NSE', '26009', 'NIFTY BANK', 'Nifty Bank', 'INDEX', None),
            self.raw_row('NCX', '71003', 'GUARSEED10', 'GUARSEED1026OCTSPD', 'FUTSPD', '20-OCT-2026'),
        ]

    def raw_row(self, exchange, token, symbol, trading_symbol, instrument, expiry):
        """Builds one raw row in the shape of `shoonya.instruments`.

        Args:
            exchange (str): The exchange code, such as NSE, BFO or NCX.
            token (str): Shoonya's token, the exchange's own token.
            symbol (str): The `symbol` column, which can be stale on BSE derivatives.
            trading_symbol (str): The `tradingsymbol` column.
            instrument (str): The instrument code, which holds the series for cash rows.
            expiry (str | None): The expiry as `DD-MON-YYYY` text, for derivatives.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        return {
            'exchange': exchange,
            'token': token,
            'lotsize': '1',
            'symbol': symbol,
            'tradingsymbol': trading_symbol,
            'instrument': instrument,
            'ticksize': '0.05',
            'expiry': expiry,
            'optiontype': None,
            'strikeprice': None,
        }

    def run(self):
        """Prints each row's segment and identity, or where an unmatched row is filed.

        Returns:
            None: This method returns nothing.
        """
        for raw_row in self.raw_rows:
            label = f'{raw_row["exchange"]} {raw_row["tradingsymbol"]} (symbol {raw_row["symbol"]}, instrument {raw_row["instrument"]})'
            segment_configuration = self.adapter.classify(raw_row)
            if segment_configuration is None:
                exchange = self.adapter.uncategorised_exchange(raw_row)
                print(f'{label} -> no segment, filed under {exchange}_uncategorised')
                continue
            identity = self.adapter.to_identity(raw_row, segment_configuration)
            print(f'{label} -> {segment_configuration["segment"]}')
            print(f'    identity {identity}')


if __name__ == '__main__':
    BondsFundsAndRenamesExample().run()
