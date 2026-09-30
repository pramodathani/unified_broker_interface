"""Classifies Dhan rows that the plain rules would get wrong, and shows the filters that correct them.

Dhan's instrument file carries ISINs and explicit instrument tags, so almost every row is classified by the equality rules in `dhan.yaml`. `DhanMappingAdapter.classify` adds a few corrections on top: an NSE fund row with series EQ is moved from mutual funds to exchange traded funds, the seven "Nifty GS" bond indices and BSE index 846 are dropped from the equity indices, fixed income rows without a usable ISIN are dropped, and a BSE fund row counts as an exchange traded fund only when other brokers confirm the symbol.

That confirmation is a set of symbols that `run` normally gathers from the other brokers' tables before it classifies anything. This program sets it by hand to one symbol, GOLDBEES, so no database is needed. A row the corrections drop is not lost: `uncategorised_exchange` reads Dhan's `exch_id` column so the row lands in the uncategorised bucket of its own exchange. The MCX spread at the end matches no rule at all and is filed the same way.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/dhan/DhanMappingAdapter/example_1_filters_and_redirects.py
"""

from stock_brokers.instruments.mapping.dhan import (
    DhanMappingAdapter,
)


class FiltersAndRedirectsExample:
    """Classifies seven hand-written Dhan rows and prints where each one lands.

    Attributes:
        adapter (DhanMappingAdapter): The adapter being shown.
        raw_rows (list): The raw rows, as dictionaries of text columns.
    """

    def __init__(self):
        """Builds the adapter, sets its BSE exchange traded fund allowlist, and writes the rows.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = DhanMappingAdapter()
        self.adapter.bse_etf_symbols = {
            'GOLDBEES',
        }
        self.raw_rows = [
            self.raw_row('NSE', 'E', '1594', 'INE009A01021', 'EQUITY', 'INFY', 'ES', 'EQ'),
            self.raw_row('NSE', 'E', '10576', 'INF204KB17I5', 'EQUITY', 'NIFTYBEES', 'ETF', 'EQ'),
            self.raw_row('NSE', 'I', '41', None, 'INDEX', 'Nifty GS 10Yr', 'INDEX', None),
            self.raw_row('NSE', 'E', '15542', None, 'EQUITY', '762GS2036', 'GB', 'GB'),
            self.raw_row('BSE', 'E', '590095', 'INF204KB17J3', 'EQUITY', 'GOLDBEES', 'ETF', 'X'),
            self.raw_row('BSE', 'E', '176234', 'INF179K01XZ4', 'EQUITY', 'HDFCSTARMF', 'MF', 'X'),
            self.raw_row('MCX', 'M', '455521', None, 'SPREAD', 'GOLDM', 'SP', None),
        ]

    def raw_row(self, exchange, segment, security_id, isin, instrument, underlying_symbol, instrument_type, series):
        """Builds one raw row in the shape of `dhan.instruments`.

        Args:
            exchange (str): The `exch_id` column.
            segment (str): Dhan's one-letter segment code.
            security_id (str): Dhan's token for the row.
            isin (str | None): The ISIN, if Dhan published one.
            instrument (str): The `instrument` column.
            underlying_symbol (str): The trading symbol.
            instrument_type (str): The `instrument_type` column.
            series (str | None): The exchange series.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        return {
            'exch_id': exchange,
            'segment': segment,
            'security_id': security_id,
            'isin': isin,
            'instrument': instrument,
            'underlying_symbol': underlying_symbol,
            'symbol_name': underlying_symbol,
            'display_name': underlying_symbol,
            'instrument_type': instrument_type,
            'series': series,
            'lot_size': '1.0',
            'tick_size': '1.0',
        }

    def run(self):
        """Prints the segment each row lands in and why.

        Returns:
            None: This method returns nothing.
        """
        for raw_row in self.raw_rows:
            segment_configuration = self.adapter.classify(raw_row)
            label = f'{raw_row["exch_id"]} {raw_row["underlying_symbol"]} ({raw_row["instrument_type"]}, series {raw_row["series"]})'
            if segment_configuration is not None:
                identity = self.adapter.to_identity(raw_row, segment_configuration)
                print(f'{label} -> {segment_configuration["segment"]} as {identity}')
                continue
            exchange = self.adapter.uncategorised_exchange(raw_row)
            print(f'{label} -> no segment after the rules and filters, filed under {exchange}_uncategorised')


if __name__ == '__main__':
    FiltersAndRedirectsExample().run()
