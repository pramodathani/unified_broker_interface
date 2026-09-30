"""Classifies Zerodha rows, where one instrument type covers equities, bonds, funds and trusts alike.

Zerodha gives every NSE cash row the instrument type EQ, whether it is a share, a government bond, a mutual fund plan or an investment trust, and it has no ISIN column. `ZerodhaMappingAdapter.classify` therefore decides everything in code: on NSE by the trading symbol's suffix (`-GS` is a bond, `-RR` a trust, `-BE` still an equity), on BSE by name and symbol heuristics, and on the derivative exchanges by whether the underlying is an index. A bond is kept only when its exchange token appears in a map from token to ISIN built out of other brokers' files, because the ISIN is its identity; the second bond below is unknown to that map and is left uncategorised.

`to_identity` strips series suffixes, stores bonds under the borrowed ISIN and brings index names to the shared spelling. `to_broker_fields` falls back to the trading symbol where a bond has no name. `classify_extra` gives a BSE row whose name equals its symbol (one of the bond heuristics) its equity membership as well.

`run` normally builds the fund lists, the token map and the index lookup from the database; this program sets them by hand, so no database is needed. `uncategorised_exchange` shows where a dropped row is filed.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/zerodha/ZerodhaMappingAdapter/example_1_one_flat_bucket_many_segments.py
"""

from stock_brokers.instruments.mapping.zerodha import (
    ZerodhaMappingAdapter,
)


class OneFlatBucketManySegmentsExample:
    """Classifies eight hand-written Zerodha rows and prints each one's segments, identity and broker symbol.

    Attributes:
        adapter (ZerodhaMappingAdapter): The adapter being shown.
        raw_rows (list): The raw rows, as dictionaries of text columns.
    """

    def __init__(self):
        """Builds the adapter, sets the lists and maps `run` would build, and writes the rows.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = ZerodhaMappingAdapter()
        self.adapter.nse_fund_symbols = set()
        self.adapter.nse_etf_symbols = set()
        self.adapter.bse_fund_symbols = set()
        self.adapter.bse_trust_symbols = set()
        self.adapter.bse_fixed_income_symbols = set()
        self.adapter.bse_etf_symbols = set()
        self.adapter.nse_index_master_lookup = {}
        self.adapter.isin_by_token = {
            '15542': 'IN0020160019',
            '973412': 'INE530B07393',
        }
        self.raw_rows = [
            self.raw_row('408065', '1594', 'INFY', 'INFOSYS', 'EQ', 'NSE', 'NSE', None, None),
            self.raw_row('3677697', '14366', 'IDEA-BE', 'VODAFONE IDEA', 'EQ', 'NSE', 'NSE', None, None),
            self.raw_row('3978753', '15542', '762GS2036-GS', None, 'EQ', 'NSE', 'NSE', None, None),
            self.raw_row('3982849', '15558', '718GS2033-GS', None, 'EQ', 'NSE', 'NSE', None, None),
            self.raw_row('2455041', '9383', 'EMBASSY-RR', 'EMBASSY OFFICE PARKS REIT', 'EQ', 'NSE', 'NSE', None, None),
            self.raw_row('260105', '26009', 'NIFTY BANK', 'NIFTY BANK', 'EQ', 'INDICES', 'NSE', None, None),
            self.raw_row('12602626', '49229', 'NIFTY26OCT25000CE', 'NIFTY', 'CE', 'NFO-OPT', 'NFO', '2026-10-27', '25000'),
            self.raw_row('249193988', '973412', '800IIFL28', '800IIFL28', 'EQ', 'BSE', 'BSE', None, None),
        ]

    def raw_row(self, instrument_token, exchange_token, trading_symbol, name, instrument_type, segment, exchange, expiry, strike):
        """Builds one raw row in the shape of `zerodha.instruments`.

        Args:
            instrument_token (str): Zerodha's own token.
            exchange_token (str): The exchange's token for the row.
            trading_symbol (str): The `tradingsymbol` column.
            name (str | None): The `name` column, blank on many bonds.
            instrument_type (str): EQ, FUT, CE or PE.
            segment (str): The `segment` column, such as NSE, INDICES or NFO-OPT.
            exchange (str): The `exchange` column.
            expiry (str | None): The expiry date as text, for derivatives.
            strike (str | None): The strike price, for options.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        return {
            'instrument_token': instrument_token,
            'exchange_token': exchange_token,
            'tradingsymbol': trading_symbol,
            'name': name,
            'expiry': expiry,
            'strike': strike,
            'tick_size': '0.01',
            'lot_size': '1',
            'instrument_type': instrument_type,
            'segment': segment,
            'exchange': exchange,
        }

    def run(self):
        """Prints each row's segments, identity and broker symbol, or where an unmatched row is filed.

        Returns:
            None: This method returns nothing.
        """
        for raw_row in self.raw_rows:
            label = f'{raw_row["exchange"]} {raw_row["tradingsymbol"]} (name {raw_row["name"]})'
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
            print(f'    identity {identity}, broker symbol {broker_fields["broker_symbol"]!r}')


if __name__ == '__main__':
    OneFlatBucketManySegmentsExample().run()
