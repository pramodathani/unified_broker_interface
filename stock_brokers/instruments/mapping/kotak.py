"""
Kotak mapping adapter.

Kotak's raw file needs two field forms no other broker uses, so this adapter extends ``_field`` rather than adding them to the shared transform registry:

- ``{constant: <value>}`` supplies a fixed value where the raw file has no usable column at all, which is the case for the lot and tick sizes of the NSE commodity and currency underlying segments.
- ``{columns: [dstrikeprice, lprecision], transform: dynamic_precision_strike}`` divides the strike by ten raised to a precision that varies **per row**: two for equity and MCX commodity contracts, four for currency ones. NSE commodity options are the exception that proves the need for it — their true scale is always four decimal places even though the row reports a precision of two, so they name the fixed ``divide_by_10_thousand`` transform instead.

Expiry dates come in two flavours on this one broker. NSE contracts count seconds from 1980-01-01, which is what the ``kotak_expiry_epoch`` transform exists for; BSE and MCX contracts are plain Unix epochs and use ``unix_epoch_date``.

The classification overrides are the ISIN splits that no equality rule can express: an NSE cash row whose ISIN is fund-prefixed is an exchange traded fund rather than an equity, a BSE row confirmed as a fund by cross-broker agreement is one whatever its group says, and both bond segments require a real non-fund ISIN. ``classify_extra`` restores the dual membership that a BSE row genuinely has when it is both a real security and a confirmed exchange traded fund.
"""

from datetime import date as date_class

import pandas as pd

from stock_brokers.instruments.mapping.base import BrokerMappingAdapter
from stock_brokers.instruments.mapping.utilities.crossref import known_bse_etf_symbols

NSE_CASH_SUFFIX_SEGMENTS = (
    "nse_equities",
    "nse_exchange_traded_funds",
    "nse_investment_trusts",
    "nse_mutual_funds",
)

NSE_NON_BOND_GROUPS = (
    "EQ",
    "SM",
    "BE",
    "ST",
    "BZ",
    "SZ",
    "E1",
    "IT",
    "W1",
    "MF",
    "SF",
    "IV",
    "RR",
    "BL",
)

BSE_INDEX_ALIASES = {
    "SENSEX50": "SNSX50",
}


def isin_is_fund(isin):
    """
    Check whether an ISIN belongs to the fund family, which India marks with an INF prefix.

    Args:
        isin (str | None): The raw ISIN value from a Kotak row.

    Returns:
        bool: True when the ISIN is present and starts with "INF".
    """
    if isin is None or pd.isna(isin):
        return False
    return str(isin).startswith("INF")


def isin_valid_bond(isin):
    """
    Check whether an ISIN can identify a bond, meaning it is present and is not a fund ISIN.

    Args:
        isin (str | None): The raw ISIN value from a Kotak row.

    Returns:
        bool: True when the ISIN is usable as a fixed income identity.
    """
    if isin is None or pd.isna(isin):
        return False
    return not str(isin).startswith("INF")


class KotakMappingAdapter(BrokerMappingAdapter):
    """Mapping adapter for Kotak, covering 31 real segments plus the uncategorised buckets."""

    BROKER_NAME = "kotak"

    def run(self, mapping_date):
        """
        Map Kotak's raw rows for one date, precomputing the BSE exchange traded fund allowlist first.

        Args:
            mapping_date (datetime.date): The raw snapshot date to map.

        Returns:
            dict: The run summary, as described in BrokerMappingAdapter.run.
        """
        with self.engine.connect() as connection:
            self.bse_etf_symbols = known_bse_etf_symbols(connection, mapping_date)
        return super().run(mapping_date)

    def _field(self, raw_row, specification):
        """
        Read one raw column value, adding Kotak's two broker-local field forms to the shared ones.

        Args:
            raw_row (dict): One raw row from kotak.instruments.
            specification: A bare column name, a {column, transform} pair, a {constant} value, or a {columns, transform} pair.

        Returns:
            The resolved value.

        Raises:
            ValueError: If a multi-column specification names a transform this adapter does not implement.
        """
        if isinstance(specification, dict):
            if "constant" in specification:
                return specification["constant"]
            if "columns" in specification:
                transform = specification["transform"]
                if transform != "dynamic_precision_strike":
                    raise ValueError(f"kotak: unknown multi-column transform {transform!r}")
                raw_strike = raw_row.get(specification["columns"][0])
                precision = raw_row.get(specification["columns"][1])
                if raw_strike is None or pd.isna(raw_strike) or precision is None or pd.isna(precision):
                    return None
                return float(raw_strike) / (10 ** float(precision))
        return super()._field(raw_row, specification)

    def classify(self, raw_row):
        """
        Classify a raw row, applying the ISIN splits and the cross-broker fund reroutes on top of the rules.

        Args:
            raw_row (dict): One raw row from kotak.instruments.

        Returns:
            dict | None: The matched segment configuration, or None when no segment matches.
        """
        segment_configuration = super().classify(raw_row)
        if segment_configuration is not None:
            segment = segment_configuration["segment"]
            group = raw_row.get("pgroup")
            isin = raw_row.get("pisin")
            symbol = raw_row.get("ptrdsymbol")

            if segment == "nse_equities":
                if isin_is_fund(isin):
                    return self.segment_config("nse_exchange_traded_funds")
                return segment_configuration
            if segment == "bse_equities":
                if group == "B" and symbol in self.bse_etf_symbols:
                    return self.segment_config("bse_exchange_traded_funds")
                if isin_is_fund(isin):
                    return None
                return segment_configuration
            if segment == "bse_exchange_traded_funds":
                description = str(raw_row.get("pdesc") or "")
                if description.startswith("INAV"):
                    return None
                return segment_configuration
            if segment == "bse_fixed_income":
                if group == "F" and symbol in self.bse_etf_symbols:
                    return self.segment_config("bse_exchange_traded_funds")
                if not isin_valid_bond(isin):
                    return None
                return segment_configuration
            return segment_configuration

        if raw_row.get("pexchseg") == "nse_cm":
            group = raw_row.get("pgroup")
            if group is None or pd.isna(group):
                return None
            if group not in NSE_NON_BOND_GROUPS and isin_valid_bond(raw_row.get("pisin")):
                return self.segment_config("nse_fixed_income")
        return None

    def classify_extra(self, raw_row):
        """
        Return the second segment a BSE row also belongs to when it is both a real security and a confirmed exchange traded fund.

        A group B or F row with a real non-fund ISIN whose symbol the other brokers independently confirm as an exchange traded fund is genuinely both things. ``classify`` picks the fund classification as primary, being the more specific signal; this restores the equity or bond membership rather than losing it.

        Args:
            raw_row (dict): One raw row from kotak.instruments.

        Returns:
            list[dict]: The additional segment configuration, or an empty list.
        """
        if raw_row.get("pexchseg") != "bse_cm":
            return []
        if raw_row.get("ptrdsymbol") not in self.bse_etf_symbols:
            return []
        if not isin_valid_bond(raw_row.get("pisin")):
            return []
        group = raw_row.get("pgroup")
        if group == "B":
            return [
                self.segment_config("bse_equities"),
            ]
        if group == "F":
            return [
                self.segment_config("bse_fixed_income"),
            ]
        return []

    def to_identity(self, raw_row, segment_configuration):
        """
        Build the unified identity fields, stripping Kotak's trading symbol suffix and applying the BSE index alias.

        Kotak appends the group to its NSE cash trading symbols, so "NBIFIN-EQ" has to lose the "-EQ" before it can converge with the other brokers' plain symbol.

        Args:
            raw_row (dict): One raw row from kotak.instruments.
            segment_configuration (dict): The segment configuration whose identity mapping applies.

        Returns:
            dict: Identity fields, as described in BrokerMappingAdapter.to_identity.

        Raises:
            ValueError: If an expiry value is numeric with no explicit transform.
        """
        identity = super().to_identity(raw_row, segment_configuration)
        segment = segment_configuration["segment"]
        if segment in NSE_CASH_SUFFIX_SEGMENTS:
            symbol = raw_row.get("ptrdsymbol")
            group = raw_row.get("pgroup")
            if symbol and group and str(symbol).endswith(f"-{group}"):
                identity["symbol"] = str(symbol)[: -(len(str(group)) + 1)]
        elif segment == "bse_equity_indices":
            identity["symbol"] = BSE_INDEX_ALIASES.get(identity["symbol"], identity["symbol"])
        return identity

    def uncategorised_exchange(self, raw_row):
        """
        Determine the canonical exchange for an unmatched Kotak row from its exchange segment column.

        Args:
            raw_row (dict): One raw row from kotak.instruments.

        Returns:
            str | None: "nse", "bse", or "mcx", or None for any other value.
        """
        exchange_segment = raw_row.get("pexchseg")
        if exchange_segment in ("nse_cm", "nse_fo", "nse_com", "cde_fo"):
            return "nse"
        if exchange_segment in ("bse_cm", "bse_fo"):
            return "bse"
        if exchange_segment == "mcx_fo":
            return "mcx"
        return None


if __name__ == "__main__":
    import argparse

    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--date", type=str, default=None)
    arguments = argument_parser.parse_args()
    KotakMappingAdapter().run(date_class.fromisoformat(arguments.date) if arguments.date else date_class.today())
