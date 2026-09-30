"""Reads the extra attributes out of one raw Dhan instrument row and expands them for a caller.

A broker's instrument file carries more than an order needs. `extract` picks out the columns `RawAttributes` knows for that broker and renames them to the shared vocabulary, so Dhan's `sm_freeze_qty` becomes `freeze_quantity` and its `asm_gsm_category` becomes `surveillance_category`. Values are kept as text, stripped of spaces, and a column that is empty in the row is left out rather than stored as null.

`fill` then turns the stored attributes back into the full vocabulary of sixteen names, with None for anything Dhan does not publish, which is the shape the REST API answers with. `columns_for` shows the column map the extraction followed.

The row is a made-up but realistic Dhan row for INFY on NSE. No database is needed.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/raw_attributes/RawAttributes/example_1_reading_a_dhan_row.py
"""

from stock_brokers.instruments.mapping.utilities.raw_attributes import (
    RawAttributes,
)


class ReadingADhanRowExample:
    """Extracts, prints and fills the attributes of one Dhan row.

    Attributes:
        raw_attributes (RawAttributes): The column map being shown.
        raw_row (dict): One raw row from Dhan's instrument table.
    """

    def __init__(self):
        """Builds the column map and the raw row.

        Returns:
            None: This method returns nothing.
        """
        self.raw_attributes = RawAttributes()
        self.raw_row = {
            'security_id': '1594',
            'exch_id': 'NSE',
            'symbol_name': 'INFOSYS LIMITED',
            'isin': 'INE009A01021',
            'display_name': ' Infosys ',
            'instrument_type': 'ES',
            'series': 'EQ',
            'sm_freeze_qty': '',
            'sm_upper_limit': '1709.60',
            'sm_lower_limit': '1398.80',
            'underlying_security_id': None,
            'asm_gsm_category': 'NA',
            'mtf_leverage': '4.00',
        }

    def run(self):
        """Prints Dhan's column map, the extracted attributes and the filled answer.

        Returns:
            None: This method returns nothing.
        """
        columns = self.raw_attributes.columns_for('dhan')
        print('Dhan column map:')
        for attribute_name in columns:
            print(f'  {attribute_name} <- {columns[attribute_name]}')
        attributes = self.raw_attributes.extract('dhan', self.raw_row)
        print(f'Stored: {attributes}')
        filled = self.raw_attributes.fill(attributes)
        print('Answered:')
        for attribute_name in filled:
            print(f'  {attribute_name}: {filled[attribute_name]}')


if __name__ == '__main__':
    ReadingADhanRowExample().run()
