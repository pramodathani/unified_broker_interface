"""
Shoonya mapping adapter.

Shoonya carries no ISIN column, so both fixed income segments take their identity from the shared security identifier map that pools the ISIN-bearing brokers' files for the same date, and a row whose identifier that map cannot resolve is left uncategorised rather than written under a ticker-keyed identity that would never converge.

Three further conditions are code-driven:

- Genuine exchange traded funds sit inside the same instrument codes as plain equities, so both fund segments are decided by cross-broker name allowlists, checked before the rules engine runs.
- NSE bonds are matched by instrument code list, a blank code, or a code starting with N, Y, or Z, which no equality rule expresses.
- BSE derivative rows carry a stale ``symbol`` column that does not track renames, so their underlying is extracted from the trading symbol by pattern instead.

Expiry dates are ``DD-MON-YYYY`` text on every derivative segment, parsed by the ``day_month_name_year_date`` transform rather than by the generic parser.
"""

import re
from datetime import date as date_class

import pandas as pd

from stock_brokers.instruments.mapping.base import BrokerMappingAdapter
from stock_brokers.instruments.mapping.utilities.crossref import (
    equity_index_lookup,
    known_bse_etf_symbols,
    known_bse_fund_symbols,
    known_nse_etf_symbols,
    known_nse_fund_symbols,
    security_id_to_isin,
)

MONTH_NAMES = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"
FUTURE_UNDERLYING_PATTERN = re.compile(rf"^(.+?)\d{{2}}(?:{MONTH_NAMES})FUT$")
OPTION_UNDERLYING_PATTERN = re.compile(rf"^(.+?)\d{{2}}(?:{MONTH_NAMES})\d+(?:\.\d+)?(?:CE|PE)$")
INDEX_OPTION_UNDERLYING_PATTERN = re.compile(
    rf"^(.+?)\d{{2}}(?:(?:{MONTH_NAMES})|[1-9OND]\d{{2}})\d+(?:\.\d+)?(?:CE|PE)$"
)

NSE_FIXED_INCOME_INSTRUMENTS = (
    "GB",
    "GS",
    "SG",
    "TB",
    "AK",
    "AL",
    "AM",
    "AN",
    "AZ",
    "BA",
    "BC",
    "BR",
    "BS",
    "BU",
    "BV",
    "BW",
    "BX",
)

NSE_BOND_INSTRUMENT_PATTERN = re.compile(r"^[NYZ]")

NSE_INDEX_ALIASES = {
    "NIFTYBANK": "BANKNIFTY",
    "NIFTYINDEX": "NIFTY",
}

BSE_FUTURE_SEGMENTS = (
    "bse_equity_futures",
    "bse_equity_index_futures",
)


def normalize_index_name(name):
    """
    Reduce an index name to uppercase alphanumerics so that differently-spelled broker names collide.

    Args:
        name (str): The raw index name.

    Returns:
        str: The name with every non-alphanumeric character removed and uppercased.
    """
    return re.sub(r"[^A-Z0-9]", "", str(name or "").upper())


class ShoonyaMappingAdapter(BrokerMappingAdapter):
    """Mapping adapter for Shoonya, covering 25 real segments plus the uncategorised buckets."""

    BROKER_NAME = "shoonya"

    def run(self, mapping_date):
        """
        Map Shoonya's raw rows for one date, precomputing the four allowlists, the ISIN map, and the index lookup first.

        Args:
            mapping_date (datetime.date): The raw snapshot date to map.

        Returns:
            dict: The run summary, as described in BrokerMappingAdapter.run.
        """
        with self.engine.connect() as connection:
            self.nse_fund_symbols = known_nse_fund_symbols(connection, mapping_date)
            self.bse_fund_symbols = known_bse_fund_symbols(connection, mapping_date)
            self.nse_etf_symbols = known_nse_etf_symbols(connection, mapping_date)
            self.bse_etf_symbols = known_bse_etf_symbols(connection, mapping_date)
            self.isin_by_token = security_id_to_isin(connection, mapping_date)
            self.nse_index_master_lookup = equity_index_lookup(connection, mapping_date)


        return super().run(mapping_date)

    def classify(self, raw_row):
        """
        Classify a raw row, checking the fund allowlists and the bond condition before the rules engine.

        Args:
            raw_row (dict): One raw row from shoonya.instruments.

        Returns:
            dict | None: The matched segment configuration, or None when no segment matches.
        """
        exchange = raw_row.get("exchange")
        instrument = raw_row.get("instrument")
        if instrument is not None and pd.isna(instrument):
            instrument = None
        token = str(raw_row.get("token"))

        if exchange == "BSE" and (instrument == "E" or raw_row.get("tradingsymbol") in self.bse_etf_symbols):
            return self.segment_config("bse_exchange_traded_funds")
        if exchange == "NSE" and raw_row.get("symbol") in self.nse_etf_symbols:
            return self.segment_config("nse_exchange_traded_funds")

        if exchange == "NSE" and self._is_nse_bond_instrument(instrument):
            if token in self.isin_by_token:
                return self.segment_config("nse_fixed_income")
            return None

        segment_configuration = super().classify(raw_row)
        if segment_configuration is None:
            return None

        segment = segment_configuration["segment"]
        if segment == "nse_equities" and raw_row.get("symbol") in self.nse_fund_symbols:
            return None
        if segment == "bse_equities" and raw_row.get("tradingsymbol") in self.bse_fund_symbols:
            return None
        if segment == "bse_fixed_income" and token not in self.isin_by_token:
            return None
        return segment_configuration

    def _is_nse_bond_instrument(self, instrument):
        """
        Check whether an NSE instrument code marks a bond.

        Args:
            instrument (str | None): The raw instrument code, already normalized so a missing value is None.

        Returns:
            bool: True when the code is a known bond code, is absent, or starts with N, Y, or Z.
        """
        if instrument is None:
            return True
        if instrument in NSE_FIXED_INCOME_INSTRUMENTS:
            return True
        return bool(NSE_BOND_INSTRUMENT_PATTERN.match(str(instrument)))

    def to_identity(self, raw_row, segment_configuration):
        """
        Build the unified identity fields, substituting the resolved ISIN, extracting BSE underlyings, and resolving index names.

        Args:
            raw_row (dict): One raw row from shoonya.instruments.
            segment_configuration (dict): The segment configuration whose identity mapping applies.

        Returns:
            dict: Identity fields, as described in BrokerMappingAdapter.to_identity.

        Raises:
            ValueError: If an expiry value is numeric with no explicit transform.
        """
        segment = segment_configuration["segment"]
        token = str(raw_row.get("token"))

        if segment in ("bse_fixed_income", "nse_fixed_income"):
            return {
                "symbol": self.isin_by_token[token],
            }

        identity = super().to_identity(raw_row, segment_configuration)
        trading_symbol = raw_row.get("tradingsymbol") or ""

        if segment in BSE_FUTURE_SEGMENTS:
            match = FUTURE_UNDERLYING_PATTERN.match(trading_symbol)
            identity["underlying_symbol"] = match.group(1) if match else None
        elif segment == "bse_equity_options":
            match = OPTION_UNDERLYING_PATTERN.match(trading_symbol)
            identity["underlying_symbol"] = match.group(1) if match else None
        elif segment == "bse_equity_index_options":
            match = INDEX_OPTION_UNDERLYING_PATTERN.match(trading_symbol)
            identity["underlying_symbol"] = match.group(1) if match else None
        elif segment == "nse_equity_indices":
            normalized = normalize_index_name(trading_symbol)
            if normalized in NSE_INDEX_ALIASES:
                identity["symbol"] = NSE_INDEX_ALIASES[normalized]
            elif normalized in self.nse_index_master_lookup:
                identity["symbol"] = self.nse_index_master_lookup[normalized]
            else:
                identity["symbol"] = trading_symbol
        return identity

    def uncategorised_exchange(self, raw_row):
        """
        Determine the canonical exchange for an unmatched Shoonya row from its exchange column.

        Args:
            raw_row (dict): One raw row from shoonya.instruments.

        Returns:
            str | None: "nse", "bse", "mcx", or "ncdex", or None for any other value.
        """
        exchange_identifier = raw_row.get("exchange")
        if exchange_identifier in ("NSE", "NFO", "CDS"):
            return "nse"
        if exchange_identifier in ("BSE", "BFO"):
            return "bse"
        if exchange_identifier == "MCX":
            return "mcx"
        if exchange_identifier == "NCX":
            return "ncdex"
        return None


if __name__ == "__main__":
    import argparse

    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--date", type=str, default=None)
    arguments = argument_parser.parse_args()
    ShoonyaMappingAdapter().run(date_class.fromisoformat(arguments.date) if arguments.date else date_class.today())
