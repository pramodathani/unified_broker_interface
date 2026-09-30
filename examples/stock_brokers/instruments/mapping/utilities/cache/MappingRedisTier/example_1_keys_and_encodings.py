"""Prints every Redis key the mapping cache uses for one day, and how each value is encoded and decoded.

A `MappingRedisTier` is the only code that reads or writes the mapping cache's Redis keys, so the names and value layouts it builds are the whole contract between the daily warm and the readers. This program asks it for every key of one mapping date and then round-trips one identity, one set of order handles, one set of additional attributes, one contract size decision, one pair of seen dates and one catalogue member through the encoders and decoders.

None of these methods talk to Redis, so the tier is built around a connection whose client is a stand-in that is never used. Notice three things in the output. The strike in a catalogue member is zero-padded so that sorting the text sorts the strikes numerically. A catalogue prefix stops at the first field that is not given, so a name alone matches every contract under it. And a value held in an older, narrower shape decodes to None, which the cache treats as a miss rather than as a wrong answer. `seconds_until_midnight()` depends on the clock, so the program prints only that it is at least sixty.

Run it from the project root:

    python examples/stock_brokers/instruments/mapping/utilities/cache/MappingRedisTier/example_1_keys_and_encodings.py
"""

import datetime
import decimal

from stock_brokers.instruments.mapping.utilities.cache import (
    MappingRedisConnection,
    MappingRedisTier,
)


class UnusedClient:
    """A stand-in Redis client that none of the methods shown here ever calls."""


class KeysAndEncodingsExample:
    """Prints the tier's keys for one date and round-trips each kind of stored value.

    Attributes:
        tier (MappingRedisTier): The tier being shown.
        mapping_date (datetime.date): The mapping date the keys are built for.
        option_identity (dict): The identity of one NIFTY option.
        equity_identity (dict): The identity of one NSE equity.
    """

    def __init__(self):
        """Builds the tier and the two identities.

        Returns:
            None: This method returns nothing.
        """
        self.tier = MappingRedisTier(MappingRedisConnection(UnusedClient()))
        self.mapping_date = datetime.date(2026, 9, 30)
        self.option_identity = {
            'instrument_id': '5f0c7a8e-3b1d-4c62-9e4a-2d8b7f1c0a31',
            'exchange': 'nse',
            'segment': 'nse_equity_index_options',
            'shape': 'option',
            'symbol': None,
            'underlying_symbol': 'NIFTY',
            'expiry_date': datetime.date(2026, 10, 6),
            'strike_price': decimal.Decimal('25000'),
            'option_type': 'CE',
            'mapping_date': self.mapping_date,
        }
        self.equity_identity = {
            'instrument_id': '0a6e2d41-9c7f-4b58-8d13-6f2e4a9b7c05',
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
            'symbol': 'INFY',
            'underlying_symbol': None,
            'expiry_date': None,
            'strike_price': None,
            'option_type': None,
            'mapping_date': self.mapping_date,
        }

    def print_keys(self):
        """Prints every key the tier builds for the mapping date.

        Returns:
            None: This method returns nothing.
        """
        print(f'Key prefix: {self.tier.KEY_PREFIX}')
        print(f'current_date_key: {self.tier.current_date_key()}')
        print(f'warm_identifier_key: {self.tier.warm_identifier_key()}')
        print(f'identity_key: {self.tier.identity_key(self.mapping_date)}')
        print(f'tokens_key: {self.tier.tokens_key(self.mapping_date, "zerodha")}')
        print(f'order_handles_key: {self.tier.order_handles_key(self.mapping_date)}')
        print(f'contract_sizes_key: {self.tier.contract_sizes_key(self.mapping_date)}')
        print(f'underlyings_key: {self.tier.underlyings_key(self.mapping_date)}')
        print(f'additional_attributes_key: {self.tier.additional_attributes_key(self.mapping_date)}')
        print(f'segments_key: {self.tier.segments_key(self.mapping_date)}')
        print(f'catalogue_key: {self.tier.catalogue_key(self.mapping_date, "nse_equities")}')
        print(f'names_key: {self.tier.names_key(self.mapping_date, "nse_equity_index_options")}')
        print(f'seen_key: {self.tier.seen_key(self.mapping_date)}')

    def print_catalogue_encoding(self):
        """Prints the catalogue names, members and prefixes of the two identities.

        Returns:
            None: This method returns nothing.
        """
        print(f'Catalogue name of the equity: {self.tier.catalogue_name(self.equity_identity)}')
        print(f'Catalogue name of the option: {self.tier.catalogue_name(self.option_identity)}')
        equity_member = self.tier.encode_catalogue_member(self.equity_identity)
        option_member = self.tier.encode_catalogue_member(self.option_identity)
        print(f'Equity member: {equity_member}')
        print(f'Option member: {option_member}')
        print(f'Instrument id read back from the option member: {self.tier.decode_catalogue_member(option_member)}')
        print(f'Prefix for a name alone: {self.tier.catalogue_prefix("NIFTY")}')
        expiry_prefix = self.tier.catalogue_prefix('NIFTY', datetime.date(2026, 10, 6))
        print(f'Prefix for a name and an expiry: {expiry_prefix}')
        whole_prefix = self.tier.catalogue_prefix(
            'NIFTY',
            datetime.date(2026, 10, 6),
            decimal.Decimal('25000'),
            'CE',
        )
        print(f'Prefix for a whole option: {whole_prefix}')
        print(f'The option member starts with it: {option_member.startswith(whole_prefix)}')

    def print_value_encodings(self):
        """Round-trips an identity, order handles, attributes, a contract size and seen dates.

        Returns:
            None: This method returns nothing.
        """
        encoded_identity = self.tier.encode_identity(self.option_identity)
        print(f'Encoded identity: {encoded_identity}')
        decoded_identity = self.tier.decode_identity(encoded_identity)
        print(f'Decoded expiry and strike: {decoded_identity["expiry_date"]!r} {decoded_identity["strike_price"]!r}')
        print(f'Decoding text that is not JSON: {self.tier.decode_identity("not json")}')
        handles = {
            'zerodha': {
                'broker_token': '12053250',
                'order_symbol': 'NIFTY26O0625000CE',
                'lot_size': '75',
                'tick_size': '0.05',
            },
        }
        encoded_handles = self.tier.encode_order_handles(handles)
        print(f'Encoded order handles: {encoded_handles}')
        print(f'Decoded order handles: {self.tier.decode_order_handles(encoded_handles)}')
        older_shape = '{"zerodha": "12053250"}'
        print(f'Decoding a bare token in the older shape: {self.tier.decode_order_handles(older_shape)}')
        attributes = {
            'dhan': {
                'freeze_quantity': '1800',
                'isin': None,
            },
        }
        encoded_attributes = self.tier.encode_additional_attributes(attributes)
        print(f'Encoded additional attributes: {encoded_attributes}')
        print(f'Decoded additional attributes: {self.tier.decode_additional_attributes(encoded_attributes)}')
        print(f'Decoding a list: {self.tier.decode_additional_attributes("[1, 2]")}')
        size = self.tier.encode_contract_size(decimal.Decimal('1000.000'), 'confirmed', True)
        print(f'Encoded contract size: {size}')
        no_source = self.tier.encode_contract_size(None, 'no_source', False)
        print(f'Encoded contract size with no source: {no_source}')
        seen = self.tier.encode_seen(datetime.date(2024, 1, 2), self.mapping_date)
        print(f'Encoded seen dates: {seen}')
        print(f'Keys live at least a minute: {self.tier.seconds_until_midnight() >= 60}')

    def run(self):
        """Prints the keys, then the catalogue encoding, then the value encodings.

        Returns:
            None: This method returns nothing.
        """
        self.print_keys()
        self.print_catalogue_encoding()
        self.print_value_encodings()


if __name__ == '__main__':
    KeysAndEncodingsExample().run()
