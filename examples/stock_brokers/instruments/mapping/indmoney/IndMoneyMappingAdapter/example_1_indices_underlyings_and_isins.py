"""Classifies IND Money rows, which have no index marker, no underlying column and, on older dates, no ISIN.

IND Money marks an index only by writing the index's own name, such as "Nifty Next 50", into its `segment` column where other rows hold E for the cash market or D for derivatives. `IndMoneyMappingAdapter.classify` therefore treats any row whose segment is neither as an index, and `to_identity` reads the name from that column and brings it to the spelling shared with other brokers. Derivatives have no underlying column, so the underlying is taken from the trading symbol, and expiries are month-first text such as `11/24/2026 14:30`.

IND Money only began publishing ISINs on 2026-09-02. `resolved_isin` reads the row's own ISIN where there is one and otherwise looks the security id up in a map built from other brokers' files. That decides whether a bond can be identified at all, and whether an equity row is really a fund and should be left uncategorised.

`run` normally builds the fund lists, the security id map and the index name lookup from the database. This program sets them by hand, so no database is needed; the security id map knows one government bond, 15542. `uncategorised_exchange` shows where a dropped row is filed.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/indmoney/IndMoneyMappingAdapter/example_1_indices_underlyings_and_isins.py
"""

from stock_brokers.instruments.mapping.indmoney import (
    IndMoneyMappingAdapter,
)


class IndicesUnderlyingsAndIsinsExample:
    """Classifies six hand-written IND Money rows and prints each one's segment and identity.

    Attributes:
        adapter (IndMoneyMappingAdapter): The adapter being shown.
        raw_rows (list): The raw rows, as dictionaries of text columns.
    """

    def __init__(self):
        """Builds the adapter, sets the lists and maps `run` would build, and writes the rows.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = IndMoneyMappingAdapter()
        self.adapter.nse_etf_symbols = set()
        self.adapter.bse_etf_symbols = set()
        self.adapter.nse_index_master_lookup = {}
        self.adapter.isin_by_security_id = {
            '15542': 'IN0020160019',
        }
        self.raw_rows = [
            self.raw_row('NSE', 'E', '2885', 'EQUITY', 'ES', 'EQ', 'RELIANCE', 'INE002A01018', None),
            self.raw_row('NSE', 'Nifty Next 50', '26013', 'INDEX', 'INDEX', None, 'NIFTY NEXT 50', None, None),
            self.raw_row('NSE', 'D', '41907', 'OPTSTK', 'OP', None, '360ONE-Nov2026-1000-CE', None, '11/24/2026 14:30'),
            self.raw_row('BSE', 'D', '1143927', 'OPTIDX', 'OPTIDX', None, 'BANKEX-24Sep2026-57200-CE', None, '09/24/2026 14:30'),
            self.raw_row('NSE', 'E', '15542', 'EQUITY', 'GB', 'GS', '762GS2036', None, None),
            self.raw_row('NSE', 'E', '26401', 'EQUITY', 'ES', 'EQ', 'LIQUIDCASE', 'INF0R8F01034', None),
        ]

    def raw_row(self, exchange, segment, security_id, instrument_name, instrument_type, series, trading_symbol, isin, expiry):
        """Builds one raw row in the shape of `indmoney.instruments`.

        Args:
            exchange (str): The `exch` column.
            segment (str): E, D, or an index's own name.
            security_id (str): IND Money's token, the exchange's security id.
            instrument_name (str): The `instrument_name` column.
            instrument_type (str): The `sem_exch_instrument_type` column.
            series (str | None): The exchange series.
            trading_symbol (str): The `trading_symbol` column.
            isin (str | None): The ISIN, blank on snapshots before 2026-09-02.
            expiry (str | None): The expiry as month-first text, for derivatives.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        strike_price = None
        option_type = None
        if trading_symbol.endswith('-CE'):
            strike_price = trading_symbol.split('-')[2]
            option_type = 'CE'
        return {
            'exch': exchange,
            'segment': segment,
            'security_id': security_id,
            'instrument_name': instrument_name,
            'trading_symbol': trading_symbol,
            'lot_units': '1',
            'custom_symbol': trading_symbol,
            'expiry_date': expiry,
            'strike_price': strike_price,
            'option_type': option_type,
            'tick_size': '5.0',
            'sem_exch_instrument_type': instrument_type,
            'series': series,
            'symbol_name': trading_symbol,
            'isin': isin,
        }

    def run(self):
        """Prints each row's resolved ISIN, segment and identity, or where an unmatched row is filed.

        Returns:
            None: This method returns nothing.
        """
        for raw_row in self.raw_rows:
            label = f'{raw_row["exch"]} {raw_row["trading_symbol"]} (segment {raw_row["segment"]!r})'
            print(label)
            print(f'    ISIN on the row {raw_row["isin"]}, resolved {self.adapter.resolved_isin(raw_row)}')
            segment_configuration = self.adapter.classify(raw_row)
            if segment_configuration is None:
                exchange = self.adapter.uncategorised_exchange(raw_row)
                print(f'    no segment, filed under {exchange}_uncategorised')
                continue
            identity = self.adapter.to_identity(raw_row, segment_configuration)
            print(f'    {segment_configuration["segment"]} as {identity}')


if __name__ == '__main__':
    IndicesUnderlyingsAndIsinsExample().run()
