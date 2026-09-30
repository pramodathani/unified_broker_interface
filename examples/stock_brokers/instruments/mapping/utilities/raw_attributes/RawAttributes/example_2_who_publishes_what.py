"""Finds which brokers publish an attribute, and shows how missing and messy values are cleaned.

`publishers_of` answers questions such as "which brokers can tell me an ISIN?" from the column map, in the map's order. `columns_for` returns an empty map for a broker the map does not know, so extracting from such a broker gives nothing rather than an error.

`clean` is the rule every value goes through: None, a pandas missing value and blank text all become None, and anything else becomes stripped text. The program also extracts a Zerodha row, whose file has only two extra columns, and a Groww row with a pandas missing value in it, to show those rules at work. The rows are made up; no database is needed.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/raw_attributes/RawAttributes/example_2_who_publishes_what.py
"""

import math

import pandas as pd

from stock_brokers.instruments.mapping.utilities.raw_attributes import (
    RawAttributes,
)


class WhoPublishesWhatExample:
    """Lists the publishers of three attributes, cleans a few values and extracts two rows.

    Attributes:
        raw_attributes (RawAttributes): The column map being shown.
    """

    def __init__(self):
        """Builds the column map.

        Returns:
            None: This method returns nothing.
        """
        self.raw_attributes = RawAttributes()

    def run(self):
        """Prints the publishers, the cleaned values and two extractions.

        Returns:
            None: This method returns nothing.
        """
        attribute_names = [
            'isin',
            'freeze_quantity',
            'buy_allowed',
        ]
        for attribute_name in attribute_names:
            print(f'{attribute_name}: {self.raw_attributes.publishers_of(attribute_name)}')
        values = [
            None,
            pd.NA,
            math.nan,
            '   ',
            ' 1800 ',
            25,
        ]
        for value in values:
            print(f'clean({value!r}) = {self.raw_attributes.clean(value)!r}')
        print(f'Columns for an unknown broker: {self.raw_attributes.columns_for("upstox")}')
        zerodha_row = {
            'instrument_token': '408065',
            'tradingsymbol': 'INFY',
            'name': 'INFOSYS',
            'instrument_type': 'EQ',
            'lot_size': '1',
        }
        print(f'Zerodha: {self.raw_attributes.extract("zerodha", zerodha_row)}')
        groww_row = {
            'exchange_token': '1594',
            'isin': 'INE009A01021',
            'name': 'Infosys',
            'instrument_type': 'EQ',
            'series': 'EQ',
            'freeze_quantity': pd.NA,
            'underlying_exchange_token': '',
            'buy_allowed': '1',
            'sell_allowed': '1',
        }
        print(f'Groww: {self.raw_attributes.extract("groww", groww_row)}')


if __name__ == '__main__':
    WhoPublishesWhatExample().run()
