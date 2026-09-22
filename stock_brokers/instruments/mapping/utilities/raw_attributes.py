"""
The extra instrument attributes each broker publishes, under one shared vocabulary.

A broker's instrument file carries far more than the mapping needs to place an order. Dhan sends an
ISIN, a freeze quantity and a price band; Kotak sends margin percentages; Groww says whether an
instrument may be bought and sold at all. None of that reaches `unified.broker_mappings`, because the
mapping only keeps the token, the symbols, the lot size and the tick size.

This module names the columns worth keeping and gives every broker's spelling of them one unified
name, so that an ISIN is `isin` whether the broker called it `isin`, `pisin` or `isin_code`. The
attributes are read at mapping time, where the raw row is already in hand, because there is no stable
key to find that row again afterwards: a broker's token is not unique within a snapshot for seven of
the ten brokers, and the symbol columns the mapping stores change from segment to segment.

Every attribute in `ATTRIBUTE_NAMES` is present for every broker, and a broker that does not publish
one has None there, which is the same rule the tick, order and position contracts follow.
"""

import pandas as pd

ATTRIBUTE_NAMES = (
    "isin",
    "display_name",
    "instrument_type",
    "series",
    "freeze_quantity",
    "price_band_high",
    "price_band_low",
    "multiplier",
    "underlying_token",
    "surveillance_category",
    "permitted_to_trade",
    "buy_allowed",
    "sell_allowed",
    "intraday_leverage",
    "margin_trading_leverage",
    "pledge_eligible",
)


class RawAttributes:
    """
    The map from each broker's raw instrument columns onto the shared attribute vocabulary.

    Attributes:
        COLUMNS (dict): Mapping of broker name to a dict of unified attribute name to that broker's column name. A broker's dict names only the attributes it publishes.
    """

    COLUMNS = {
        "dhan": {
            "isin": "isin",
            "display_name": "display_name",
            "instrument_type": "instrument_type",
            "series": "series",
            "freeze_quantity": "sm_freeze_qty",
            "price_band_high": "sm_upper_limit",
            "price_band_low": "sm_lower_limit",
            "underlying_token": "underlying_security_id",
            "surveillance_category": "asm_gsm_category",
            "margin_trading_leverage": "mtf_leverage",
        },
        "kotak": {
            "isin": "pisin",
            "display_name": "pdesc",
            "instrument_type": "pinsttype",
            "freeze_quantity": "lfreezeqty",
            "price_band_high": "dhighpricerange",
            "price_band_low": "dlowpricerange",
            "multiplier": "lmultiplier",
            "surveillance_category": "surveillancemessage",
            "permitted_to_trade": "ipermittedtotrade",
            "pledge_eligible": "caseligible",
        },
        "groww": {
            "isin": "isin",
            "display_name": "name",
            "instrument_type": "instrument_type",
            "series": "series",
            "freeze_quantity": "freeze_quantity",
            "underlying_token": "underlying_exchange_token",
            "buy_allowed": "buy_allowed",
            "sell_allowed": "sell_allowed",
        },
        "stoxkart": {
            "isin": "isin_code",
            "display_name": "symbol_description",
            "instrument_type": "instrument_type",
            "series": "series",
        },
        "fyers": {
            "isin": "isin",
            "display_name": "symbol_details",
            "instrument_type": "exchange_instrument_type",
            "underlying_token": "underlying_scrip_code",
        },
        "wisdom_capital": {
            "isin": "isin",
            "display_name": "description",
            "instrument_type": "instrumenttype",
            "series": "series",
            "freeze_quantity": "freezeqty",
            "price_band_high": "priceband_high",
            "price_band_low": "priceband_low",
            "multiplier": "multiplier",
            "underlying_token": "underlyinginstrumentid",
            "surveillance_category": "gsmindicator",
        },
        "indmoney": {
            "isin": "isin",
            "display_name": "custom_symbol",
            "instrument_type": "sem_exch_instrument_type",
            "series": "series",
            "freeze_quantity": "freeze_qty",
            "price_band_high": "upper_limit",
            "price_band_low": "lower_limit",
            "multiplier": "general_factor",
            "intraday_leverage": "intraday_leverage",
            "pledge_eligible": "pledge_eligible",
        },
        "flattrade": {
            "instrument_type": "instrument",
        },
        "shoonya": {
            "instrument_type": "instrument",
            "multiplier": "multiplier",
        },
        "zerodha": {
            "display_name": "name",
            "instrument_type": "instrument_type",
        },
    }

    def columns_for(self, broker):
        """Finds the raw columns one broker publishes attributes in.

        Args:
            broker (str): The broker name, as it appears in unified.broker_mappings.

        Returns:
            dict: Mapping of unified attribute name to that broker's column name, empty when the broker publishes nothing beyond what the mapping already keeps.
        """
        return self.COLUMNS.get(broker, {})

    def publishers_of(self, attribute_name):
        """Finds every broker that publishes one attribute.

        Args:
            attribute_name (str): A name from ATTRIBUTE_NAMES.

        Returns:
            list[str]: The broker names, in the order the column map lists them.
        """
        brokers = []
        for broker in self.COLUMNS:
            if attribute_name in self.COLUMNS[broker]:
                brokers.append(broker)
        return brokers

    def extract(self, broker, raw_row):
        """Reads one broker's extra attributes out of one raw instrument row.

        Only the attributes this broker actually published are in the answer. An attribute it does not publish at all, and one whose column is empty in this row, is left out rather than stored as null, because writing all sixteen names for every broker on every instrument costs about three times what the values themselves do. The endpoint fills the missing names back in from ATTRIBUTE_NAMES, so a caller still sees every name.

        Values are kept as the broker sent them, stripped of surrounding whitespace and turned into text, because a raw instrument table stores every column as text and nothing here is a number to compute with.

        Args:
            broker (str): The broker name, as it appears in unified.broker_mappings.
            raw_row (dict): One raw row from that broker's instrument table.

        Returns:
            dict: Mapping of unified attribute name to a string value, holding only the attributes this broker published for this row.
        """
        columns = self.columns_for(broker)
        attributes = {}
        for attribute_name in ATTRIBUTE_NAMES:
            column_name = columns.get(attribute_name)
            if column_name is None:
                continue
            value = self.clean(raw_row.get(column_name))
            if value is not None:
                attributes[attribute_name] = value
        return attributes

    def clean(self, value):
        """Turns one raw column value into the text stored for it, or None.

        Args:
            value (object): The value as the raw instrument table returned it, which may be None, a pandas missing value, or text.

        Returns:
            str | None: The value as stripped text, or None when it is missing or empty.
        """
        if value is None:
            return None
        if not isinstance(value, (list, tuple, dict)) and pd.isna(value):
            return None
        text_value = str(value).strip()
        if text_value == "":
            return None
        return text_value

    def fill(self, attributes):
        """Expands stored attributes back to the full vocabulary, for an answer a caller reads.

        Storage keeps only what a broker published; a caller should not have to check whether a name is there before reading it. This is the one place the two shapes meet.

        Args:
            attributes (dict): The attributes as stored, holding only the names the broker published.

        Returns:
            dict: Mapping of every name in ATTRIBUTE_NAMES to its stored value or None.
        """
        filled = {}
        for attribute_name in ATTRIBUTE_NAMES:
            filled[attribute_name] = attributes.get(attribute_name)
        return filled
