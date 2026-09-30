"""The orders every broker's margin calculator is asked about, built from today's catalogue and live quotes."""

import datetime
import decimal
import json

from unified_broker_interface.utilities.broker_orders.utilities.instrument import (
    Instrument,
)
from unified_broker_interface.utilities.margin_calculators.utilities.reference_leg import (
    ReferenceLeg,
)

QUOTES_KEY = 'unified:quotes:live'
CURRENT_DATE_KEY = 'unified:catalogue:current_date'
CONDOR_STEP = decimal.Decimal(100)


class ReferenceOrders:
    """Builds the reference orders from Redis: one for each margin category, and an iron condor to test hedge benefit.

    The same orders go to every broker, at the same prices, so the brokers' answers can be compared with each other. The exchange's margin is taken to be what most brokers agree on, and each broker's surcharge is its answer divided by that.

    | Category | Order |
    |---|---|
    | `intraday` | Buy 1 INFY share, `MIS` |
    | `fno` | Sell 1 lot of the nearest NIFTY future, `NRML` |
    | `commodity` | Buy 1 lot of the nearest crude oil future, `NRML` |
    | hedge benefit | A NIFTY iron condor on the nearest weekly expiry after today: calls and puts 200 points either side of the index bought and 400 points either side sold, one lot each, bought legs first |

    Attributes:
        cache (redis.Redis): The Redis client.
        mapping_date (str): Today's catalogue date.
        today (datetime.date): The day the orders are built for.
    """

    def __init__(self, cache, today=None):
        """Builds the reader for today's catalogue.

        Args:
            cache (redis.Redis): The Redis client.
            today (datetime.date | None): The day, or None for today.

        Returns:
            None: This method returns nothing.

        Raises:
            ValueError: When no catalogue date is published.
        """
        self.cache = cache
        mapping_date = self.text(cache.get(CURRENT_DATE_KEY))
        if not mapping_date:
            raise ValueError(f'{CURRENT_DATE_KEY} is not set, so no instruments are mapped yet')
        self.mapping_date = mapping_date
        self.today = today or datetime.date.today()

    @staticmethod
    def text(value):
        """A Redis reply as text.

        Args:
            value (str | bytes | None): The reply.

        Returns:
            str: The text, or an empty string for None.
        """
        if value is None:
            return ''
        if isinstance(value, bytes):
            return value.decode()
        return str(value)

    def catalogue_key(self, name):
        """A key of today's catalogue.

        Args:
            name (str): The key's last part, such as `identity`.

        Returns:
            str: The key.
        """
        return f'unified:catalogue:{self.mapping_date}:{name}'

    def members(self, segment, prefix):
        """The catalogue members of a segment whose text starts with a prefix.

        Args:
            segment (str): The segment, such as `nse_equity_index_futures`.
            prefix (str): The start of the member, such as `NIFTY|`.

        Returns:
            list: The members (str), each `symbol|expiry|strike|type|instrument_id`.
        """
        found = self.cache.zrangebylex(
            self.catalogue_key(f'catalogue:{segment}'),
            f'[{prefix}',
            f'[{prefix}\xff',
        )
        members = []
        for member in found:
            members.append(self.text(member))
        return members

    def instrument(self, instrument_id):
        """An instrument with every broker's order handle, from today's catalogue.

        Args:
            instrument_id (str): The instrument's id.

        Returns:
            Instrument: The instrument.

        Raises:
            RefusedRequestError: With HTTP 404 when the instrument is not mapped.
        """
        pipeline = self.cache.pipeline(transaction=False)
        pipeline.hget(self.catalogue_key('identity'), instrument_id)
        pipeline.hget(self.catalogue_key('order_handles'), instrument_id)
        pipeline.hget(self.catalogue_key('contract_sizes'), instrument_id)
        identity_text, handles_text, contract_size_text = pipeline.execute()
        return Instrument.decoded(
            instrument_id,
            self.text(identity_text),
            self.text(handles_text),
            self.text(contract_size_text),
        )

    def quote(self, instrument_id):
        """An instrument's live quote.

        Args:
            instrument_id (str): The instrument's id.

        Returns:
            dict | None: The quote, or None when none is held.
        """
        quote_text = self.text(self.cache.hget(QUOTES_KEY, instrument_id))
        if not quote_text:
            return None
        try:
            quote = json.loads(quote_text)
        except ValueError:
            return None
        if not isinstance(quote, dict) or quote.get('last_price') is None:
            return None
        return quote

    def nearest_expiry_member(self, segment, prefix, after):
        """The member with the earliest expiry on or after a day.

        Args:
            segment (str): The segment.
            prefix (str): The start of the member.
            after (datetime.date): The earliest acceptable expiry.

        Returns:
            str | None: The member, or None when none expires on or after the day.
        """
        chosen = None
        for member in self.members(segment, prefix):
            expiry_text = member.split('|')[1]
            if not expiry_text or expiry_text < after.isoformat():
                continue
            if chosen is None or expiry_text < chosen.split('|')[1]:
                chosen = member
        return chosen

    def leg_for(self, name, member, transaction_type, product, lots):
        """A leg for a catalogue member, priced at its last trade, or None when it has no quote.

        Args:
            name (str): The leg's short name.
            member (str | None): The catalogue member.
            transaction_type (str): `BUY` or `SELL`.
            product (str): The product.
            lots (int): How many lots, or shares for an equity.

        Returns:
            ReferenceLeg | None: The leg.
        """
        if member is None:
            return None
        instrument_id = member.split('|')[-1]
        quote = self.quote(instrument_id)
        if quote is None:
            return None
        instrument = self.instrument(instrument_id)
        lot_size = int(decimal.Decimal(str(quote.get('lot_size') or 1)))
        units_per_lot = instrument.trusted_units_per_lot()
        if units_per_lot is not None:
            lot_size = int(units_per_lot)
        price = decimal.Decimal(str(quote['last_price']))
        return ReferenceLeg(name, instrument, transaction_type, product, lots * lot_size, price)

    def intraday_leg(self):
        """Buy 1 INFY share, `MIS`.

        Returns:
            ReferenceLeg | None: The leg, or None when INFY has no quote.
        """
        members = self.members('nse_equities', 'INFY|')
        member = None
        if members:
            member = members[0]
        return self.leg_for('INFY bought intraday', member, 'BUY', 'MIS', 1)

    def fno_leg(self):
        """Sell 1 lot of the nearest NIFTY future.

        Returns:
            ReferenceLeg | None: The leg, or None when there is no quote.
        """
        member = self.nearest_expiry_member('nse_equity_index_futures', 'NIFTY|', self.today)
        return self.leg_for('NIFTY future sold', member, 'SELL', 'NRML', 1)

    def commodity_leg(self):
        """Buy 1 lot of the nearest crude oil future.

        Returns:
            ReferenceLeg | None: The leg, or None when there is no quote.
        """
        member = self.nearest_expiry_member('mcx_commodity_futures', 'CRUDEOIL|', self.today)
        return self.leg_for('crude oil future bought', member, 'BUY', 'NRML', 1)

    def condor_legs(self, index_level):
        """A NIFTY iron condor around an index level, bought legs first.

        Args:
            index_level (decimal.Decimal): Where NIFTY is, such as the future's price.

        Returns:
            list | None: The four `ReferenceLeg` legs, or None when an option is missing or has no quote.
        """
        after = self.today + datetime.timedelta(days=1)
        first = self.nearest_expiry_member('nse_equity_index_options', 'NIFTY|', after)
        if first is None:
            return None
        expiry = first.split('|')[1]
        centre = (index_level / CONDOR_STEP).quantize(decimal.Decimal(1)) * CONDOR_STEP
        wanted = [
            ('bought call', centre + 4 * CONDOR_STEP, 'CE', 'BUY'),
            ('bought put', centre - 4 * CONDOR_STEP, 'PE', 'BUY'),
            ('sold call', centre + 2 * CONDOR_STEP, 'CE', 'SELL'),
            ('sold put', centre - 2 * CONDOR_STEP, 'PE', 'SELL'),
        ]
        legs = []
        for name, strike_price, option_type, transaction_type in wanted:
            prefix = f'NIFTY|{expiry}|{strike_price:016.4f}|{option_type}|'
            members = self.members('nse_equity_index_options', prefix)
            member = None
            if members:
                member = members[0]
            leg = self.leg_for(f'NIFTY {strike_price} {option_type} {name}', member, transaction_type, 'NRML', 1)
            if leg is None:
                return None
            legs.append(leg)
        return legs
