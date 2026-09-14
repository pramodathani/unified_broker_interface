"""
Wisdom Capital mapping adapter.

Wisdom Capital reports instrument type as a numeric code — 1 for futures, 2 for options, 16 for underlying references — and lumps several segments into one code and exchange segment pair. The canonical segment order lists the general segment first in every one of those pairs, so listing order cannot separate them, and the separation is stated here instead, as an explicit table of redirects from the general segment to the specific one by underlying name.

The redirects cover twelve cases: index derivatives on all three exchanges, currency derivatives that share the rate derivative code, and the overnight rate index futures.

The rest of this adapter is the logic no rule can express:

- NSE cash equities carry fund contamination, separated by the ISIN's INF prefix, and the same symbol can appear under two series at once. The duplicate is resolved by reading the rows worst-series-first, so the best series is written last and wins.
- BSE cash rows have no native fund or trust marker at all, so both are cross-broker allowlists; bonds are the F and G series with a real ISIN; and equities are a clean series list, or the B series with a non-fund ISIN, after dropping the duplicate rows whose name ends in a hash.
- NSE fixed income merges two raw sources: cash bonds identified by ISIN, and the rate derivative underlying references identified by name, which carry no real lot or tick size.
- Option types are the numeric codes 3 and 4, remapped to CE and PE.
- The BSE rate futures segments carry placeholder rows that are not real contracts, dropped by matching the description against a single-leg contract pattern.
"""

import re
from datetime import date as date_class

import pandas as pd
from sqlalchemy import text

from stock_brokers.instruments.mapping.base import BrokerMappingAdapter
from stock_brokers.instruments.mapping.utilities.crossref import known_bse_etf_symbols, known_bse_investment_trust_symbols

OPTION_TYPES = {
    "3": "CE",
    "4": "PE",
}

CURRENCY_NAMES = (
    "EURINR",
    "EURUSD",
    "GBPINR",
    "GBPUSD",
    "JPYINR",
    "USDINR",
    "USDJPY",
)

NSE_INDEX_NAMES = (
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTY",
    "NIFTYFPI",
    "NIFTYNXT50",
)

BSE_INDEX_NAMES = (
    "BANKEX",
    "SENSEX",
    "SENSEX50",
    "FOCIT",
)

MCX_INDEX_NAMES = (
    "MCXALUMDEX",
    "MCXGOLDEX",
    "MCXBULLDEX",
    "MCXCOMPDEX",
    "MCXMETLDEX",
    "MCXZINCDEX",
    "MCXSILVDEX",
    "MCXCOPRDEX",
    "MCXLEADEX",
    "MCXNGASDEX",
    "MCXENRGDEX",
    "MCXCRUDEX",
)

MCX_INDEX_DERIVATIVE_NAMES = (
    "MCXBULLDEX",
    "MCXMETLDEX",
)

OVERNIGHT_RATE_NAMES = (
    "ONMIBOR",
)

NAME_REDIRECTS = (
    ("nse_equity_futures", NSE_INDEX_NAMES, "nse_equity_index_futures"),
    ("nse_equity_options", NSE_INDEX_NAMES, "nse_equity_index_options"),
    ("bse_equity_futures", BSE_INDEX_NAMES, "bse_equity_index_futures"),
    ("bse_equity_options", BSE_INDEX_NAMES, "bse_equity_index_options"),
    ("mcx_commodities", MCX_INDEX_NAMES, "mcx_commodity_indices"),
    ("mcx_commodity_futures", MCX_INDEX_DERIVATIVE_NAMES, "mcx_commodity_index_futures"),
    ("mcx_commodity_options", MCX_INDEX_DERIVATIVE_NAMES, "mcx_commodity_index_options"),
    ("nse_fixed_income_futures", CURRENCY_NAMES, "nse_currency_futures"),
    ("nse_fixed_income_futures", OVERNIGHT_RATE_NAMES, "nse_fixed_income_index_futures"),
    ("bse_fixed_income_futures", CURRENCY_NAMES, "bse_currency_futures"),
    ("bse_fixed_income_futures", OVERNIGHT_RATE_NAMES, "bse_fixed_income_index_futures"),
    ("bse_fixed_income_options", CURRENCY_NAMES, "bse_currency_options"),
)

SERIES_PRIORITY = (
    "EQ",
    "T0",
    "BE",
    "ST",
    "SM",
    "BZ",
    "SZ",
    "IT",
    "W1",
    "E1",
)

CLEAN_BSE_EQUITY_SERIES = (
    "A",
    "M",
    "MS",
    "MT",
    "NS",
    "NT",
    "P",
    "R",
    "T",
    "TS",
    "X",
    "XT",
    "Y",
    "Z",
    "ZP",
)

NSE_NON_BOND_SERIES = (
    "EQ",
    "SM",
    "BE",
    "ST",
    "BZ",
    "SZ",
    "E1",
    "IT",
    "W1",
    "T0",
    "MF",
    "SF",
    "IV",
    "RR",
)

BSE_INDEX_ALIASES = {
    "BASMTR": "COMDTY",
    "CDGS": "CONDIS",
    "FIN": "FINSER",
}

MONTH_NAMES = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"
SINGLE_LEG_FUTURE_PATTERN = re.compile(rf"^[A-Z0-9]+\d{{2}}(?:(?:{MONTH_NAMES})|[1-9OND]\d{{2}})FUT$")

RATE_UNDERLYING_SUFFIXES = (
    "-UNDIRC",
    "-UNDIRT",
)

NULL_LOT_AND_TICK_SEGMENTS = (
    "nse_commodities",
    "nse_currencies",
    "nse_fixed_income_indices",
)

NULL_TICK_SEGMENTS = (
    "bse_equity_indices",
)


def isin_is_fund(raw_row):
    """
    Check whether a row's ISIN belongs to the fund family.

    Args:
        raw_row (dict): One raw row from wisdom_capital.instruments.

    Returns:
        bool: True when the ISIN is present and starts with "INF".
    """
    isin = raw_row.get("isin")
    if isin is None or pd.isna(isin):
        return False
    return str(isin).startswith("INF")


def isin_valid_bond(raw_row):
    """
    Check whether a row carries an ISIN usable as a fixed income identity.

    Args:
        raw_row (dict): One raw row from wisdom_capital.instruments.

    Returns:
        bool: True when the ISIN is present and is not a fund ISIN.
    """
    isin = raw_row.get("isin")
    if isin is None or pd.isna(isin) or str(isin).strip() == "":
        return False
    return not str(isin).startswith("INF")


class WisdomCapitalMappingAdapter(BrokerMappingAdapter):
    """Mapping adapter for Wisdom Capital, covering 41 real segments plus the uncategorised buckets."""

    BROKER_NAME = "wisdom_capital"

    def run(self, mapping_date):
        """
        Map Wisdom Capital's raw rows for one date, precomputing the two BSE allowlists first.

        Args:
            mapping_date (datetime.date): The raw snapshot date to map.

        Returns:
            dict: The run summary, as described in BrokerMappingAdapter.run.
        """
        with self.engine.connect() as connection:
            self.bse_etf_symbols = known_bse_etf_symbols(connection, mapping_date)
            self.bse_trust_symbols = known_bse_investment_trust_symbols(connection, mapping_date)
        return super().run(mapping_date)

    def read_raw_rows(self, connection, mapping_date):
        """
        Read Wisdom Capital's rows worst-series-first, so the highest-priority series wins where one symbol is listed twice.

        A cash-market symbol can appear under two series at once, for example EQ and T0 together. The run collapses rows onto one identity keeping the last one written, so ordering the read by descending series priority makes the preferred series the survivor.

        Args:
            connection (sqlalchemy.engine.Connection): An open SQLAlchemy connection.
            mapping_date (datetime.date): The raw snapshot date to read.

        Returns:
            pandas.DataFrame: The raw rows, ordered by descending series priority.
        """
        raw = pd.read_sql(
            text("SELECT * FROM wisdom_capital.instruments WHERE download_date = :d"),
            connection,
            params={
                "d": mapping_date,
            },
        )
        if raw.empty:
            return raw

        priorities = []
        for series in raw["series"]:
            if series in SERIES_PRIORITY:
                priorities.append(SERIES_PRIORITY.index(series))
            else:
                priorities.append(len(SERIES_PRIORITY))
        raw = raw.assign(series_priority=priorities)
        raw = raw.sort_values("series_priority", ascending=False, kind="stable")
        return raw.drop(columns=["series_priority"])

    def classify(self, raw_row):
        """
        Classify a raw row, applying the name redirects and then the code-driven checks for the segments with no rules.

        Args:
            raw_row (dict): One raw row from wisdom_capital.instruments.

        Returns:
            dict | None: The matched segment configuration, or None when no segment matches.
        """
        segment_configuration = super().classify(raw_row)
        if segment_configuration is not None:
            segment = segment_configuration["segment"]
            name = raw_row.get("name")

            for matched_segment, names, target_segment in NAME_REDIRECTS:
                if segment == matched_segment and name in names:
                    return self.segment_config(target_segment)

            if segment == "nse_equities" and isin_is_fund(raw_row):
                return self.segment_config("nse_exchange_traded_funds")
            if segment in ("bse_fixed_income_futures", "bse_fixed_income_index_futures"):
                description = raw_row.get("description") or ""
                if not SINGLE_LEG_FUTURE_PATTERN.match(str(description)):
                    return None
            if segment == "nse_commodities" and name == "11NSETEST":
                return None
            return segment_configuration

        exchange_segment = raw_row.get("exchangesegment")
        if exchange_segment == "NSECM":
            return self._classify_nse_cash(raw_row)
        if exchange_segment == "NSECD":
            return self._classify_nse_currency_derivatives(raw_row)
        if exchange_segment == "BSECM":
            return self._classify_bse_cash(raw_row)
        return None

    def _classify_nse_cash(self, raw_row):
        """
        Classify an NSE cash-market row no rule claimed, which is a bond when its series is not an equity series and its ISIN is real.

        Args:
            raw_row (dict): One raw row from wisdom_capital.instruments.

        Returns:
            dict | None: The fixed income segment configuration, or None.
        """
        series = raw_row.get("series")
        if series is None or pd.isna(series):
            return None
        if series in NSE_NON_BOND_SERIES:
            return None
        if not isin_valid_bond(raw_row):
            return None
        return self.segment_config("nse_fixed_income")

    def _classify_nse_currency_derivatives(self, raw_row):
        """
        Classify an NSE currency-segment underlying reference row, which is a rate derivative underlying rather than a currency or a rate index.

        Args:
            raw_row (dict): One raw row from wisdom_capital.instruments.

        Returns:
            dict | None: The fixed income segment configuration, or None.
        """
        if raw_row.get("instrumenttype") != "16":
            return None
        if raw_row.get("name") in OVERNIGHT_RATE_NAMES:
            return None
        description = str(raw_row.get("description") or "")
        for suffix in RATE_UNDERLYING_SUFFIXES:
            if description.endswith(suffix):
                return self.segment_config("nse_fixed_income")
        return None

    def _classify_bse_cash(self, raw_row):
        """
        Classify a BSE cash-market row, which carries no native fund, trust, or bond marker.

        Args:
            raw_row (dict): One raw row from wisdom_capital.instruments.

        Returns:
            dict | None: The matched segment configuration, or None.
        """
        name = raw_row.get("name") or ""
        series = raw_row.get("series")

        if name in self.bse_etf_symbols:
            return self.segment_config("bse_exchange_traded_funds")
        if name in self.bse_trust_symbols:
            return self.segment_config("bse_investment_trusts")
        if series in ("F", "G") and isin_valid_bond(raw_row):
            return self.segment_config("bse_fixed_income")
        if str(name).endswith("#"):
            return None
        if series in CLEAN_BSE_EQUITY_SERIES:
            return self.segment_config("bse_equities")
        if series == "B" and not isin_is_fund(raw_row):
            return self.segment_config("bse_equities")
        return None

    def to_identity(self, raw_row, segment_configuration):
        """
        Build the unified identity fields, choosing the fixed income identity per source and remapping the numeric option type.

        Args:
            raw_row (dict): One raw row from wisdom_capital.instruments.
            segment_configuration (dict): The segment configuration whose identity mapping applies.

        Returns:
            dict: Identity fields, as described in BrokerMappingAdapter.to_identity.

        Raises:
            ValueError: If an expiry value is numeric with no explicit transform.
        """
        segment = segment_configuration["segment"]

        if segment == "nse_fixed_income":
            if raw_row.get("exchangesegment") == "NSECM":
                return {
                    "symbol": str(raw_row.get("isin")).strip(),
                }
            return {
                "symbol": str(raw_row.get("name")).strip(),
            }

        identity = super().to_identity(raw_row, segment_configuration)
        if segment == "bse_equity_indices":
            identity["symbol"] = BSE_INDEX_ALIASES.get(identity["symbol"], identity["symbol"])
        if segment_configuration["shape"] == "option":
            raw_code = identity.get("option_type")
            identity["option_type"] = OPTION_TYPES.get(str(raw_code), raw_code)
        return identity

    def to_broker_fields(self, raw_row, segment_configuration):
        """
        Build the per-broker mapping fields, forcing the sizes to nothing on the segments whose rows are not directly tradeable.

        The BSE equity indices carry a tick of 1 on every row whatever the index's real tick, so their tick is dropped and their lot size kept.

        Args:
            raw_row (dict): One raw row from wisdom_capital.instruments.
            segment_configuration (dict): The segment configuration whose broker field mapping applies.

        Returns:
            dict: Keys "broker_token" (str), "broker_symbol", "lot_size" (float | None), and "tick_size" (float | None).
        """
        broker_fields = super().to_broker_fields(raw_row, segment_configuration)
        segment = segment_configuration["segment"]
        is_rate_underlying = segment == "nse_fixed_income" and raw_row.get("exchangesegment") == "NSECD"
        if segment in NULL_LOT_AND_TICK_SEGMENTS or is_rate_underlying:
            broker_fields["lot_size"] = None
            broker_fields["tick_size"] = None
        if segment in NULL_TICK_SEGMENTS:
            broker_fields["tick_size"] = None
        return broker_fields

    def uncategorised_exchange(self, raw_row):
        """
        Determine the canonical exchange for an unmatched Wisdom Capital row from its exchange segment column.

        Args:
            raw_row (dict): One raw row from wisdom_capital.instruments.

        Returns:
            str | None: "nse", "bse", "mcx", or "ncdex", or None for any other value.
        """
        exchange_segment = raw_row.get("exchangesegment")
        if exchange_segment in ("NSECM", "NSEFO", "NSECD", "NSECO"):
            return "nse"
        if exchange_segment in ("BSECM", "BSEFO", "BSECD"):
            return "bse"
        if exchange_segment == "MCXFO":
            return "mcx"
        if exchange_segment == "NCDEX":
            return "ncdex"
        return None


if __name__ == "__main__":
    import argparse

    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--date", type=str, default=None)
    arguments = argument_parser.parse_args()
    WisdomCapitalMappingAdapter().run(date_class.fromisoformat(arguments.date) if arguments.date else date_class.today())
