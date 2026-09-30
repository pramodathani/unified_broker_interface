"""Classifies Wisdom Capital rows, whose instrument types and option types are numeric codes shared by several segments.

Wisdom Capital writes futures as instrument type 1, options as 2 and underlying references as 16, and one code within one exchange segment covers several of this project's segments: NIFTY options and stock options, or currency futures and rate futures. `WisdomCapitalMappingAdapter.classify` lets the rules pick the general segment and then moves the row by its underlying name, using an explicit table of redirects. It also moves NSE equity rows with a fund ISIN to exchange traded funds, drops BSE rate futures whose description is not a single real contract, and classifies in code the NSE bonds, the NSE rate underlyings and every BSE cash row, none of which the rules cover.

`to_identity` turns option types 3 and 4 into CE and PE, and stores an NSE cash bond under its ISIN but a rate underlying under its name. `to_broker_fields` drops the sizes of rows that cannot be traded directly. `run` normally gathers the BSE exchange traded fund and investment trust lists from the database; this program sets them to empty by hand, so no database is needed. `uncategorised_exchange` shows where a dropped row is filed.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/wisdom_capital/WisdomCapitalMappingAdapter/example_1_redirects_and_codes.py
"""

from stock_brokers.instruments.mapping.wisdom_capital import (
    WisdomCapitalMappingAdapter,
)


class RedirectsAndCodesExample:
    """Classifies eight hand-written Wisdom Capital rows and prints each one's segment, identity and sizes.

    Attributes:
        adapter (WisdomCapitalMappingAdapter): The adapter being shown.
        raw_rows (list): The raw rows, as dictionaries of text columns.
    """

    def __init__(self):
        """Builds the adapter, sets the lists `run` would gather, and writes the rows.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = WisdomCapitalMappingAdapter()
        self.adapter.bse_etf_symbols = set()
        self.adapter.bse_trust_symbols = set()
        self.raw_rows = [
            self.raw_row('NSEFO', '40215', '2', 'NIFTY', 'NIFTY26OCT25000CE', None, None, '2026-10-27T14:30:00', '25000', '3'),
            self.raw_row('NSECD', '8801', '1', 'USDINR', 'USDINR26OCTFUT', None, None, '2026-10-28T12:00:00', None, None),
            self.raw_row('NSECM', '10576', '8', 'NIFTYBEES', 'NIFTYBEES-EQ', 'EQ', 'INF204KB14I2', None, None, None),
            self.raw_row('NSECM', '15542', '8', '762GS2036', '762GS2036-GS', 'GS', 'IN0020160019', None, None, None),
            self.raw_row('NSECD', '11001', '16', '726GS2033', '726GS2033-UNDIRC', None, None, None, None, None),
            self.raw_row('BSECD', '870001', '1', '726GS2033', '726GS2033 CONTRACT PLACEHOLDER', None, None, '2026-10-29T12:00:00', None, None),
            self.raw_row('BSECM', '999901', '8', 'FIN', 'FIN', 'SPOT', None, None, None, None),
            self.raw_row('BSECM', '543210', '8', 'OLDNAME#', 'OLDNAME#', 'A', 'INE000Y01018', None, None, None),
        ]

    def raw_row(self, exchange_segment, token, instrument_type, name, description, series, isin, expiry, strike, option_code):
        """Builds one raw row in the shape of `wisdom_capital.instruments`.

        Args:
            exchange_segment (str): The `exchangesegment` column, such as NSECM or BSECD.
            token (str): The `exchangeinstrumentid` column, the exchange's token.
            instrument_type (str): Wisdom Capital's numeric instrument type.
            name (str): The `name` column, the symbol or underlying.
            description (str): The `description` column.
            series (str | None): The exchange series, for cash rows.
            isin (str | None): The ISIN.
            expiry (str | None): The `contractexpiration` column, for derivatives.
            strike (str | None): The strike price, for options.
            option_code (str | None): 3 for a call or 4 for a put.

        Returns:
            dict: The raw row, every column as text as the raw table stores it.
        """
        return {
            'exchangesegment': exchange_segment,
            'exchangeinstrumentid': token,
            'instrumenttype': instrument_type,
            'name': name,
            'description': description,
            'series': series,
            'ticksize': '0.05',
            'lotsize': '1',
            'displayname': description,
            'isin': isin,
            'contractexpiration': expiry,
            'strikeprice': strike,
            'optiontype': option_code,
        }

    def run(self):
        """Prints each row's segment, identity and sizes, or where an unmatched row is filed.

        Returns:
            None: This method returns nothing.
        """
        for raw_row in self.raw_rows:
            label = f'{raw_row["exchangesegment"]} {raw_row["description"]} (type {raw_row["instrumenttype"]})'
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
    RedirectsAndCodesExample().run()
