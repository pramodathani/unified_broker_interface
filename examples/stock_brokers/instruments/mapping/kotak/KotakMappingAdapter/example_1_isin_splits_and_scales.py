"""Classifies Kotak rows whose segment depends on the ISIN, and reads strikes and expiries in Kotak's several scales.

Kotak's groups say little about what a row really is, so `KotakMappingAdapter.classify` looks at the ISIN: an NSE equity-group row with a fund ISIN is an exchange traded fund, a BSE row with one is left uncategorised, bonds need a real non-fund ISIN, and BSE group E rows whose description starts with "INAV" (an indicative value, not a fund) are dropped. A BSE row that other brokers confirm as an exchange traded fund but that also has a company ISIN is both things, and `classify_extra` returns its second segment.

`to_identity` strips Kotak's group suffix, so `NBIFIN-EQ` is stored as NBIFIN. Behind it, Kotak's field reader handles the scales: an NSE expiry counts seconds from 1980-01-01, a BSE one from 1970, and a BSE option strike is divided by ten raised to the row's own precision. Kotak's currency underlying rows have no lot or tick size, so both are stored as None.

`run` normally gathers the BSE exchange traded fund list from the database; this program sets it by hand to one symbol, so no database is needed. `uncategorised_exchange` shows where a dropped row is filed. The dual-membership row is shaped by hand to show the case; its symbol is made up.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/kotak/KotakMappingAdapter/example_1_isin_splits_and_scales.py
"""

from stock_brokers.instruments.mapping.kotak import (
    KotakMappingAdapter,
)


class IsinSplitsAndScalesExample:
    """Classifies eight hand-written Kotak rows and prints each one's segments, identity and sizes.

    Attributes:
        adapter (KotakMappingAdapter): The adapter being shown.
        raw_rows (list): The raw rows, as dictionaries of text columns.
    """

    def __init__(self):
        """Builds the adapter, sets the list `run` would gather, and writes the rows.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = KotakMappingAdapter()
        self.adapter.bse_etf_symbols = {
            'DUALETF',
        }
        self.raw_rows = [
            self.raw_row('nse_cm', 'NSE', 'EQ', None, '4749', 'NBIFIN-EQ', 'NBIFIN', 'INE918K01019', 'BAJAJ HOLDINGS'),
            self.raw_row('nse_cm', 'NSE', 'EQ', None, '10576', 'NIFTYBEES-EQ', 'NIFTYBEES', 'INF204KB14I2', 'NIPPON INDIA ETF NIFTY 50 BEES'),
            self.raw_row('nse_cm', 'NSE', 'GS', None, '15542', '762GS2036-GS', '762GS2036', 'IN0020160019', 'GOI LOAN 7.62% 2036'),
            self.raw_row('bse_cm', 'BSE', 'E', None, '540005', 'INAVGOLD', 'INAVGOLD', None, 'INAV OF A GOLD ETF'),
            self.raw_row('bse_cm', 'BSE', 'B', None, '543999', 'DUALETF', 'DUALETF', 'INE000X01011', 'A FUND LISTED AS AN EQUITY'),
            self.raw_row('nse_fo', 'NFO', None, 'OPTIDX', '40215', 'NIFTY26OCT25000CE', 'NIFTY', None, None),
            self.raw_row('bse_fo', 'BFO', None, 'SO', '1165432', 'IRFC26OCT102.5CE', 'IRFC', None, None),
            self.raw_row('cde_fo', 'CDS', None, 'UNDCUR', '1', 'USDINR', 'USDINR', None, None),
        ]
        self.raw_rows[5]['lexpirydate'] = '1477578600'
        self.raw_rows[5]['dstrikeprice'] = '2500000'
        self.raw_rows[5]['poptiontype'] = 'CE'
        self.raw_rows[6]['lexpirydate'] = '1793268000'
        self.raw_rows[6]['dstrikeprice'] = '10250'
        self.raw_rows[6]['lprecision'] = '2'
        self.raw_rows[6]['poptiontype'] = 'CE'

    def raw_row(self, exchange_segment, exchange, group, instrument_type, token, trading_symbol, symbol_name, isin, description):
        """Builds one raw row in the shape of `kotak.instruments`.

        Args:
            exchange_segment (str): The `pexchseg` column, such as nse_cm or bse_fo.
            exchange (str): The `pexchange` column.
            group (str | None): The `pgroup` column, which holds the series for cash rows.
            instrument_type (str | None): The `pinsttype` column, for derivatives.
            token (str): The `psymbol` column, Kotak's token.
            trading_symbol (str): The `ptrdsymbol` column.
            symbol_name (str): The `psymbolname` column.
            isin (str | None): The `pisin` column.
            description (str | None): The `pdesc` column.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        return {
            'psymbol': token,
            'pgroup': group,
            'pexchseg': exchange_segment,
            'pinsttype': instrument_type,
            'psymbolname': symbol_name,
            'ptrdsymbol': trading_symbol,
            'poptiontype': None,
            'pisin': isin,
            'pdesc': description,
            'dticksize': '5',
            'llotsize': '1',
            'lexpirydate': None,
            'lprecision': None,
            'dstrikeprice': None,
            'pexchange': exchange,
        }

    def run(self):
        """Prints each row's segments, identity and sizes, or where an unmatched row is filed.

        Returns:
            None: This method returns nothing.
        """
        for raw_row in self.raw_rows:
            label = f'{raw_row["pexchseg"]} {raw_row["ptrdsymbol"]}'
            segment_configuration = self.adapter.classify(raw_row)
            if segment_configuration is None:
                exchange = self.adapter.uncategorised_exchange(raw_row)
                print(f'{label} -> no segment, filed under {exchange}_uncategorised')
                continue
            extra_segments = []
            for extra_configuration in self.adapter.classify_extra(raw_row):
                extra_segments.append(extra_configuration['segment'])
            identity = self.adapter.to_identity(raw_row, segment_configuration)
            broker_fields = self.adapter.to_broker_fields(raw_row, segment_configuration)
            print(f'{label} -> {segment_configuration["segment"]}, also {extra_segments}')
            print(f'    identity {identity}')
            print(f'    lot size {broker_fields["lot_size"]}, tick size {broker_fields["tick_size"]}')


if __name__ == '__main__':
    IsinSplitsAndScalesExample().run()
