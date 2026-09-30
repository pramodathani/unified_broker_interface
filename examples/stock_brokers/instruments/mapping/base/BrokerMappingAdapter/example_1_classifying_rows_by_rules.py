"""Classifies three raw instrument rows using nothing but a broker's rules file.

`BrokerMappingAdapter` is the base class every broker's mapping adapter subclasses. A subclass only has to name its broker in `BROKER_NAME`, and the base class loads the matching rules file from `stock_brokers/instruments/mapping/utilities/rules/`, checks it against the canonical segment vocabulary, and classifies rows by plain equality rules. This program's subclass sets `BROKER_NAME` to Dhan and overrides nothing, so every answer below comes from the base class and Dhan's rules file alone, without the extra filters the real `DhanMappingAdapter` adds.

The rows are written out by hand in the shape of `dhan.instruments`, where every column is text. The adapter builds a database engine when it is constructed, but an engine does not connect until it is used, and this program never asks it to, so nothing touches PostgreSQL.

For each row the program prints the segment the rules chose, any extra segments (the base class never adds any), the identity fields that go into the instrument id, the broker's own fields, and the deterministic instrument id. The third row matches no rule. The base class cannot tell which exchange it belongs to, so it falls into the unprefixed `uncategorised` segment, and the run would store its token as its symbol.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/base/BrokerMappingAdapter/example_1_classifying_rows_by_rules.py
"""

from stock_brokers.instruments.mapping import base
from stock_brokers.instruments.mapping.base import (
    BrokerMappingAdapter,
)


class DhanRulesOnlyAdapter(BrokerMappingAdapter):
    """A mapping adapter that uses Dhan's rules file and nothing but the base class's behaviour."""

    BROKER_NAME = 'dhan'


class ClassifyingRowsByRulesExample:
    """Runs three hand-written Dhan rows through the base class's rules engine and prints the result.

    Attributes:
        adapter (DhanRulesOnlyAdapter): The adapter being shown.
        raw_rows (list): The raw rows to classify, as dictionaries of text columns.
    """

    def __init__(self):
        """Builds the adapter and the three raw rows.

        Returns:
            None: This method returns nothing.
        """
        self.adapter = DhanRulesOnlyAdapter()
        self.raw_rows = [
            {
                'exch_id': 'NSE',
                'segment': 'E',
                'security_id': '1594',
                'isin': 'INE009A01021',
                'instrument': 'EQUITY',
                'underlying_symbol': 'INFY',
                'symbol_name': 'INFOSYS LIMITED',
                'display_name': 'Infosys',
                'instrument_type': 'ES',
                'series': 'EQ',
                'lot_size': '1.0',
                'sm_expiry_date': None,
                'strike_price': None,
                'option_type': None,
                'tick_size': '10.0',
            },
            {
                'exch_id': 'NSE',
                'segment': 'D',
                'security_id': '40215',
                'isin': None,
                'instrument': 'OPTIDX',
                'underlying_symbol': 'NIFTY',
                'symbol_name': 'NIFTY-Oct2026-25000-CE',
                'display_name': 'NIFTY 27 OCT 25000 CALL',
                'instrument_type': 'OP',
                'series': None,
                'lot_size': '75.0',
                'sm_expiry_date': '2026-10-27',
                'strike_price': '25000.00000',
                'option_type': 'CE',
                'tick_size': '5.0',
            },
            {
                'exch_id': 'NSE',
                'segment': 'X',
                'security_id': '990001',
                'isin': None,
                'instrument': 'SPREAD',
                'underlying_symbol': '',
                'symbol_name': 'TEST SPREAD',
                'display_name': 'Test spread',
                'instrument_type': 'SP',
                'series': None,
                'lot_size': '1.0',
                'sm_expiry_date': None,
                'strike_price': None,
                'option_type': None,
                'tick_size': '0',
            },
        ]

    def run(self):
        """Prints how the rules file classifies each row.

        Returns:
            None: This method returns nothing.
        """
        equities = self.adapter.segment_config('nse_equities')
        print(f'Rules file: {self.adapter.config["raw_table"]}, {len(self.adapter.config["segments"])} segments')
        print(f'nse_equities is a {equities["shape"]} on {equities["exchange"]} with {len(equities["rules"])} rules')
        print(f'Unconfigured segment: {self.adapter.segment_config("nse_bonds")}')
        for raw_row in self.raw_rows:
            print()
            print(f'Row {raw_row["security_id"]} ({raw_row["symbol_name"]})')
            segment_configuration = self.adapter.classify(raw_row)
            if segment_configuration is None:
                exchange = self.adapter.uncategorised_exchange(raw_row)
                print(f'  No rule matched, and the base class finds no exchange: {exchange}')
                segment_configuration = self.adapter.segment_config('uncategorised')
            extra_segments = self.adapter.classify_extra(raw_row)
            identity = self.adapter.to_identity(raw_row, segment_configuration)
            broker_fields = self.adapter.to_broker_fields(raw_row, segment_configuration)
            identifier = base.instrument_id(
                segment_configuration['exchange'],
                segment_configuration['segment'],
                segment_configuration['shape'],
                identity,
            )
            print(f'  Segment: {segment_configuration["segment"]} ({segment_configuration["shape"]})')
            print(f'  Extra segments: {extra_segments}')
            print(f'  Identity: {identity}')
            print(f'  Broker fields: {broker_fields}')
            print(f'  Instrument id: {identifier}')


if __name__ == '__main__':
    ClassifyingRowsByRulesExample().run()
