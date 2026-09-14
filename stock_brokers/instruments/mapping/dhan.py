"""
Dhan mapping adapter.

Dhan carries ISIN and explicit instrument tags, so its classification is almost entirely rules driven. Four segments still need a ``classify`` post-filter, for exclusions and allowlists no equality rule can express:

- ``bse_equity_indices`` drops security id 846, a duplicate and unconfirmed CAPINS index.
- ``nse_equity_indices`` drops the seven "Nifty GS ..." government securities bond indices.
- ``bse_fixed_income`` and ``nse_fixed_income`` drop rows with no ISIN or an INF-prefixed one, a defensive fund-contamination exclusion.
- ``bse_exchange_traded_funds`` needs a positive cross-broker allowlist, because Dhan's own MF and ETF instrument type bucket has no reliable internal signal to tell real exchange traded funds from BSE STAR mutual fund scheme codes.

One redirect handles the ordering interaction with the canonical segment order: ``nse_mutual_funds`` is listed before ``nse_exchange_traded_funds``, so a mutual fund or ETF instrument type row with series EQ is redirected to the exchange traded funds segment rather than relying on the YAML listing order.
"""

from datetime import date as date_class

from stock_brokers.instruments.mapping.base import BrokerMappingAdapter
from stock_brokers.instruments.mapping.utilities.crossref import known_bse_etf_symbols

EXCLUDED_BSE_INDEX_SECURITY_IDS = (
    "846",
)

EXCLUDED_NSE_GOVERNMENT_SECURITIES_INDEX_NAMES = (
    "Nifty GS 10Yr",
    "Nifty GS 10Yr Cln",
    "Nifty GS 11 15Yr",
    "Nifty GS 15YrPlus",
    "Nifty GS 4 8Yr",
    "Nifty GS 8 13Yr",
    "Nifty GS Compsite",
)


def isin_invalid(raw_row):
    """
    Check whether a raw row's ISIN is missing or is a fund-family ISIN.

    Args:
        raw_row (dict): One raw row from dhan.instruments.

    Returns:
        bool: True when the ISIN is absent or starts with "INF", meaning the row cannot be identified as fixed income by its ISIN.
    """
    isin = raw_row.get("isin")
    return not isin or str(isin).startswith("INF")


class DhanMappingAdapter(BrokerMappingAdapter):
    """Mapping adapter for Dhan, covering 27 real segments plus the uncategorised buckets."""

    BROKER_NAME = "dhan"

    def run(self, mapping_date):
        """
        Map Dhan's raw rows for one date, precomputing the BSE exchange traded fund allowlist first.

        Args:
            mapping_date (datetime.date): The raw snapshot date to map.

        Returns:
            dict: The run summary, as described in BrokerMappingAdapter.run.
        """
        with self.engine.connect() as connection:
            self.bse_etf_symbols = known_bse_etf_symbols(connection, mapping_date)
        return super().run(mapping_date)

    def classify(self, raw_row):
        """
        Classify a raw row, applying Dhan's post-filters and the mutual fund redirect on top of the rules.

        Args:
            raw_row (dict): One raw row from dhan.instruments.

        Returns:
            dict | None: The matched segment configuration, or None when no segment matches.
        """
        segment_configuration = super().classify(raw_row)
        if segment_configuration is None:
            return None
        segment = segment_configuration["segment"]
        if segment == "nse_mutual_funds" and raw_row.get("series") == "EQ":
            return self.segment_config("nse_exchange_traded_funds")
        if segment == "bse_equity_indices" and str(raw_row.get("security_id")) in EXCLUDED_BSE_INDEX_SECURITY_IDS:
            return None
        if segment == "nse_equity_indices" and raw_row.get("underlying_symbol") in EXCLUDED_NSE_GOVERNMENT_SECURITIES_INDEX_NAMES:
            return None
        if segment in ("bse_fixed_income", "nse_fixed_income") and isin_invalid(raw_row):
            return None
        if segment == "bse_exchange_traded_funds" and raw_row.get("underlying_symbol") not in self.bse_etf_symbols:
            return None
        return segment_configuration

    def uncategorised_exchange(self, raw_row):
        """
        Determine the canonical exchange for an unmatched Dhan row from its exch_id column.

        Args:
            raw_row (dict): One raw row from dhan.instruments.

        Returns:
            str | None: "nse", "bse", or "mcx", or None for any other value.
        """
        exchange_identifier = raw_row.get("exch_id")
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
    DhanMappingAdapter().run(date_class.fromisoformat(arguments.date) if arguments.date else date_class.today())