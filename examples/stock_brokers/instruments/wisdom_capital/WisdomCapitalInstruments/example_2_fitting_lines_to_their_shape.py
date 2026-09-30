"""Fits split master lines to the number of fields their shape declares with `pad_or_join_fields`.

Wisdom Capital's master lines are split on the pipe character, and each of the three row shapes declares its own number of columns: 22 for an equity, 23 for an option and 21 for a future. `WisdomCapitalInstruments.pad_or_join_fields` forces one split line to that number. A short line is padded with empty strings, and a line with too many fields, which happens when a text field itself contains a pipe, has its surplus joined back into the last field so that the frame can still be built.

The program fits three equity lines: one of the right length, one missing its last two indicators, and one whose description contains a pipe. It pairs each result with the equity column names from the module and prints the columns that change. It needs no network and no database.

Notice the third line. The pipe was in `Description`, the fifth field, but the surplus is joined into the last field, `GSMIndicator`, so every value from the description onwards lands one column to the left: `Description` holds only the first half of the text and `Series` holds the second half. This looks like a bug and is reported as one; the output records what the code does today.

Run it from the project root:

    python examples/stock_brokers/instruments/wisdom_capital/WisdomCapitalInstruments/example_2_fitting_lines_to_their_shape.py
"""

from stock_brokers.instruments.wisdom_capital import (
    EQUITY_COLUMN_NAMES,
    WisdomCapitalInstruments,
)


class FittingLinesToTheirShapeExample:
    """Fits three equity lines to the equity shape and prints the columns of interest.

    Attributes:
        instruments (WisdomCapitalInstruments): The ingester being shown.
        lines (list): Pairs of (description, pipe-delimited equity line).
        shown_columns (list): The equity columns to print for each line.
    """

    def __init__(self):
        """Builds the ingester and the lines to fit.

        Returns:
            None: This method returns nothing.
        """
        self.instruments = WisdomCapitalInstruments()
        self.lines = [
            (
                'a line of the right length',
                'NSECM|2031|8|M&M|M&M-EQ|EQ|M&M-EQ|1100100002031|3500.5|2800.4|50001|0.1|1|1|M&M|INE101A01026|1|1|MAHINDRA & MAHINDRA LTD|0|-1|-1',
            ),
            (
                'a line missing its last two indicators',
                'NSECM|2031|8|M&M|M&M-EQ|EQ|M&M-EQ|1100100002031|3500.5|2800.4|50001|0.1|1|1|M&M|INE101A01026|1|1|MAHINDRA & MAHINDRA LTD|0',
            ),
            (
                'a line whose description contains a pipe',
                'NSECM|2031|8|M&M|MAHINDRA|MAHINDRA-EQ|EQ|M&M-EQ|1100100002031|3500.5|2800.4|50001|0.1|1|1|M&M|INE101A01026|1|1|MAHINDRA & MAHINDRA LTD|0|-1|-1',
            ),
        ]
        self.shown_columns = [
            'Description',
            'Series',
            'ISIN',
            'CautionIndicator',
            'GSMIndicator',
        ]

    def run(self):
        """Fits each line and prints its field counts and chosen columns.

        Returns:
            None: This method returns nothing.
        """
        expected_count = len(EQUITY_COLUMN_NAMES)
        print(f'Equity shape: {expected_count} fields')
        for description, line in self.lines:
            fields = line.split('|')
            fitted = self.instruments.pad_or_join_fields(fields, expected_count)
            row = dict(zip(EQUITY_COLUMN_NAMES, fitted))
            print(f'{description}: {len(fields)} fields in, {len(fitted)} out')
            for column in self.shown_columns:
                print(f'    {column}: {row[column]!r}')


if __name__ == '__main__':
    FittingLinesToTheirShapeExample().run()
