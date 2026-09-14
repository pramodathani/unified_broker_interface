"""
Groww mapping adapter.

Groww mixes stock and index instruments in one FNO segment with no dedicated discriminator column, contaminates its plain equity series with INF-prefixed exchange traded funds, and needs a crossref allowlist to tell BSE exchange traded funds from similarly-tagged rows. None of that is expressible as equality rules, so this module carries the classification overrides:

- ``nse_fixed_income`` is matched by a negative-series check: an NSE cash row whose series is not one of the known equity, fund, and trust series and whose ISIN is not INF-prefixed is fixed income.
- ``bse_exchange_traded_funds`` requires the row's trading symbol to be in the cross-broker allowlist from ``known_bse_etf_symbols``.
- ``nse_exchange_traded_funds`` is the redirect target for NSE equity rows with an INF-prefixed ISIN and series EQ.
- NSE futures and options rows whose underlying is an equity index are redirected to the index segments; the same redirect handles the MCX index underlyings, because the canonical segment order lists the general commodity segments before the index ones.
- ``bse_equities`` series B rows with an INF-prefixed ISIN, ``bse_fixed_income`` rows with a missing or INF-prefixed ISIN, and the blank-symbol BSE index row are dropped into the uncategorised buckets.
- Index symbols are normalized and aliased, and the fund, trust, and mutual fund symbols carry broker-specific suffixes that are stripped in ``to_identity``.
"""

import re
from datetime import date as date_class

import pandas as pd

from stock_brokers.instruments.mapping.base import BrokerMappingAdapter
from stock_brokers.instruments.mapping.utilities.crossref import equity_index_lookup, known_bse_etf_symbols

NSE_INDEX_UNDERLYINGS = (
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTY",
    "NIFTYFPI",
    "NIFTYNXT50",
)

MCX_INDEX_UNDERLYINGS = (
    "MCXBULLDEX",
    "MCXMETLDEX",
)

NON_BOND_SERIES = (
    "EQ",
    "SM",
    "BE",
    "ST",
    "BZ",
    "SZ",
    "E1",
    "IT",
    "MF",
    "IV",
    "RR",
)

BSE_INDEX_ALIASES = {
    "BSEMIDCAP": "MIDCAP",
    "BSESMLCAP": "SMLCAP",
}

NSE_INDEX_ALIASES = {
    "MIDCAP50": "NIFTYMCAP50",
    "NIFTYCDTY": "NIFTY COMMODITIES",
    "NIFTYJR": "NIFTYNXT50",
    "NIFTYMIDCAP": "NIFTY MID100 FREE",
    "NIFTYMIDSELECT": "MIDCPNIFTY",
    "NIFTYSMALL": "NIFTY SMALLCAP 100",
    "NIFTYTOTALMCAP": "NIFTY TOTAL MKT",
}


def normalize_index_name(name):
    """
    Reduce an index name to uppercase alphanumerics so that differently-spelled broker names collide.

    Args:
        name (str): The raw index name from a broker table.

    Returns:
        str: The name with every non-alphanumeric character removed and uppercased.
    """
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


def isin_invalid(raw_row):
    """
    Check whether a raw row's ISIN is missing or is a fund-family ISIN.

    Args:
        raw_row (dict): One raw row from groww.instruments.

    Returns:
        bool: True when the ISIN is absent or starts with "INF", meaning the row cannot be identified as fixed income by its ISIN.
    """
    isin = raw_row.get("isin")
    return not isin or str(isin).startswith("INF")


class GrowwMappingAdapter(BrokerMappingAdapter):
    """Mapping adapter for Groww, covering 23 real segments plus the uncategorised buckets."""

    BROKER_NAME = "groww"

    def run(self, mapping_date):
        """
        Map Groww's raw rows for one date, precomputing the BSE exchange traded fund allowlist and the NSE index name lookup first.

        Args:
            mapping_date (datetime.date): The raw snapshot date to map.

        Returns:
            dict: The run summary, as described in BrokerMappingAdapter.run.
        """
        with self.engine.connect() as connection:
            self.bse_etf_symbols = known_bse_etf_symbols(connection, mapping_date)
            self.nse_index_master_lookup = equity_index_lookup(connection, mapping_date)
        return super().run(mapping_date)

    def classify(self, raw_row):
        """
        Classify a raw row, applying Groww's pre-checks, redirects, and exclusions on top of the rules.

        Args:
            raw_row (dict): One raw row from groww.instruments.

        Returns:
            dict | None: The matched segment configuration, or None when no segment matches.
        """
        series = raw_row.get("series")
        if (
            raw_row.get("exchange") == "NSE"
            and raw_row.get("segment") == "CASH"
            and series
            and not pd.isna(series)
            and series not in NON_BOND_SERIES
            and not isin_invalid(raw_row)
        ):
            return self.segment_config("nse_fixed_income")
        if raw_row.get("exchange") == "BSE" and raw_row.get("trading_symbol") in self.bse_etf_symbols:
            return self.segment_config("bse_exchange_traded_funds")

        segment_configuration = super().classify(raw_row)
        if segment_configuration is None:
            return None
        segment = segment_configuration["segment"]

        if segment == "nse_equities":
            isin = raw_row.get("isin")
            if isin and str(isin).startswith("INF"):
                if raw_row.get("series") == "EQ":
                    return self.segment_config("nse_exchange_traded_funds")
                return None
        if segment == "nse_equity_futures" and raw_row.get("underlying_symbol") in NSE_INDEX_UNDERLYINGS:
            return self.segment_config("nse_equity_index_futures")
        if segment == "nse_equity_options" and raw_row.get("underlying_symbol") in NSE_INDEX_UNDERLYINGS:
            return self.segment_config("nse_equity_index_options")
        if segment == "mcx_commodity_futures" and raw_row.get("underlying_symbol") in MCX_INDEX_UNDERLYINGS:
            return self.segment_config("mcx_commodity_index_futures")
        if segment == "mcx_commodity_options" and raw_row.get("underlying_symbol") in MCX_INDEX_UNDERLYINGS:
            return self.segment_config("mcx_commodity_index_options")
        if segment == "bse_equities" and raw_row.get("series") == "B" and isin_invalid(raw_row):
            return None
        if segment == "bse_equity_indices" and not raw_row.get("trading_symbol"):
            return None
        if segment == "bse_fixed_income" and isin_invalid(raw_row):
            return None
        return segment_configuration

    def to_identity(self, raw_row, segment_configuration):
        """
        Build the unified identity fields, applying Groww's index aliases, index normalization, and symbol suffix stripping.

        Args:
            raw_row (dict): One raw row from groww.instruments.
            segment_configuration (dict): The segment configuration whose identity mapping applies.

        Returns:
            dict: Identity fields, as described in BrokerMappingAdapter.to_identity.

        Raises:
            ValueError: If an expiry value is numeric with no explicit transform.
        """
        identity = super().to_identity(raw_row, segment_configuration)
        segment = segment_configuration["segment"]
        if segment == "bse_equity_indices":
            identity["symbol"] = BSE_INDEX_ALIASES.get(identity["symbol"], identity["symbol"])
        elif segment == "nse_equity_indices":
            normalized = normalize_index_name(identity["symbol"])
            if normalized in NSE_INDEX_ALIASES:
                identity["symbol"] = NSE_INDEX_ALIASES[normalized]
            else:
                identity["symbol"] = self.nse_index_master_lookup.get(normalized, identity["symbol"])
        elif segment == "nse_exchange_traded_funds":
            identity["symbol"] = re.sub(r"-EQ$", "", identity["symbol"])
        elif segment == "nse_investment_trusts":
            identity["symbol"] = re.sub(r"-IV$", "", identity["symbol"])
        elif segment == "nse_mutual_funds":
            identity["symbol"] = re.sub(r"-MF$", "", identity["symbol"])
        return identity

    def to_broker_fields(self, raw_row, segment_configuration):
        """
        Build the per-broker mapping fields, with Groww's fallback of the trading symbol when a BSE fixed income row has no name.

        Args:
            raw_row (dict): One raw row from groww.instruments.
            segment_configuration (dict): The segment configuration whose broker field mapping applies.

        Returns:
            dict: Keys "broker_token" (str), "broker_symbol", "lot_size" (float | None), and "tick_size" (float | None).
        """
        broker_fields = super().to_broker_fields(raw_row, segment_configuration)
        broker_symbol = broker_fields["broker_symbol"]
        if segment_configuration["segment"] == "bse_fixed_income" and (
            not broker_symbol or pd.isna(broker_symbol)
        ):
            broker_fields["broker_symbol"] = raw_row.get("trading_symbol")
        return broker_fields

    def uncategorised_exchange(self, raw_row):
        """
        Determine the canonical exchange for an unmatched Groww row from its exchange column.

        Args:
            raw_row (dict): One raw row from groww.instruments.

        Returns:
            str | None: "nse", "bse", or "mcx", or None for any other value.
        """
        exchange_identifier = raw_row.get("exchange")
        if exchange_identifier == "NSE":
            return "nse"
        if exchange_identifier == "BSE":
            return "bse"
        if exchange_identifier == "MCX":
            return "mcx"
        return None


if __name__ == "__main__":
    import argparse

    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--date", type=str, default=None)
    arguments = argument_parser.parse_args()
    GrowwMappingAdapter().run(date_class.fromisoformat(arguments.date) if arguments.date else date_class.today())