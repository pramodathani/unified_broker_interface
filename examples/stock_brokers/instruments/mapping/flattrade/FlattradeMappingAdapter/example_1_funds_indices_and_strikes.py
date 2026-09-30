"""Classifies Flattrade rows whose segment depends on other brokers' lists, and corrects a mis-rounded BSE strike.

Flattrade's file cannot tell an NSE equity from an exchange traded fund or a mutual fund by its own columns, so `FlattradeMappingAdapter.classify` checks the symbol against symbol sets gathered from the other brokers. It also drops the bond-shaped NSE index rows, and it files a blank-exchange row that `read_raw_rows` recovered as a BSE equity. `to_identity` then fixes two things: BSE option strikes, which Flattrade rounds (a real 102.5 arrives as 103.0), are read back from the trading symbol, and NSE index names are brought to one spelling shared with the other brokers.

`run` normally fills the symbol sets and the index name lookup from the database before it classifies anything. This program sets them by hand, so no database is needed. `uncategorised_exchange` shows which exchange's uncategorised bucket a dropped row goes to.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/flattrade/FlattradeMappingAdapter/example_1_funds_indices_and_strikes.py
"""

from stock_brokers.instruments.mapping import flattrade
from stock_brokers.instruments.mapping.flattrade import (
    FlattradeMappingAdapter,
)


class FundsIndicesAndStrikesExample:
    """Classifies eight hand-written Flattrade rows and prints each one's segment and identity.

    Attributes:
        adapter (FlattradeMappingAdapter): The adapter being shown.
        raw_rows (list): The raw rows, as dictionaries of text columns.
    """

    def __init__(self):
        """Builds the adapter, sets the lists `run` would gather, and writes the rows.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = FlattradeMappingAdapter()
        self.adapter.nse_etf_symbols = {
            'NIFTYBEES',
        }
        self.adapter.nse_fund_symbols = {
            'LIQUIDCASE',
        }
        self.adapter.bse_etf_symbols = set()
        self.adapter.bse_fund_symbols = set()
        self.adapter.nse_index_master_lookup = {
            'NIFTYBANK': 'NIFTY BANK',
        }
        recovered_row = self.raw_row('', '500325', 'RELIANCE', 'RELIANCE', '', None, None, None)
        recovered_row[flattrade.RECOVERED_BSE_EQUITY_FLAG] = True
        self.raw_rows = [
            self.raw_row('NSE', '1594', 'INFY', 'INFY-EQ', 'EQ', None, None, None),
            self.raw_row('NSE', '10576', 'NIFTYBEES', 'NIFTYBEES-EQ', 'EQ', None, None, None),
            self.raw_row('NSE', '26401', 'LIQUIDCASE', 'LIQUIDCASE-BE', 'BE', None, None, None),
            self.raw_row('NSE', '26009', 'Nifty Bank', 'Nifty Bank', 'INDEX', None, None, None),
            self.raw_row('NSE', '26071', 'NIFTY SMLCAP 100', 'NIFTY SMLCAP 100', 'INDEX', None, None, None),
            self.raw_row('NSE', '26047', 'Nifty GS 10Yr', 'Nifty GS 10Yr', 'INDEX', None, None, None),
            self.raw_row('BFO', '1165432', 'IRFC', 'IRFC26OCT102.5CE', 'OPTSTK', '27-OCT-2026', '103.00', 'CE'),
            recovered_row,
        ]

    def raw_row(self, exchange, token, symbol, trading_symbol, instrument, expiry, strike, option_type):
        """Builds one raw row in the shape of `flattrade.instruments`.

        Args:
            exchange (str): The exchange code, blank where Flattrade's file leaves it blank.
            token (str): Flattrade's token for the row.
            symbol (str): The `symbol` column.
            trading_symbol (str): The `tradingsymbol` column.
            instrument (str): The `instrument` column.
            expiry (str | None): The expiry, as `DD-MON-YYYY` text.
            strike (str | None): The strike price as Flattrade reports it.
            option_type (str | None): CE or PE for an option.

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
            'expiry': expiry,
            'strike': strike,
            'optiontype': option_type,
        }

    def run(self):
        """Prints the segment and identity of each row, or where an unmatched row is filed.

        Returns:
            None: This method returns nothing.
        """
        for raw_row in self.raw_rows:
            label = f'{raw_row["exchange"] or "(blank)"} {raw_row["tradingsymbol"]}'
            segment_configuration = self.adapter.classify(raw_row)
            if segment_configuration is None:
                exchange = self.adapter.uncategorised_exchange(raw_row)
                print(f'{label} -> no segment, filed under {exchange}_uncategorised')
                continue
            identity = self.adapter.to_identity(raw_row, segment_configuration)
            print(f'{label} -> {segment_configuration["segment"]}')
            print(f'    identity {identity}')


if __name__ == '__main__':
    FundsIndicesAndStrikesExample().run()
