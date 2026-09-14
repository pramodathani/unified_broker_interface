"""
Fyers mapping adapter.

Fyers reports exchange, segment, and instrument type as numeric codes rather than names, and this project's raw table stores them as text: exchange 10 is NSE, 11 is MCX, 12 is BSE; segment 10 is the cash market, 11 derivatives, 12 currency, 20 commodities. The rules file matches those codes as quoted strings.

Two umbrellas need code-driven routing, because one instrument type code covers several segments:

- BSE cash rows split by instrument type, and type 50 splits further on a suffix embedded in the ticker: the clean equity suffixes and a non-fund B suffix are equities, while F and G with a real ISIN are bonds. Exchange traded funds and investment trusts are drawn from any BSE row by cross-broker allowlist, checked first, except on index rows, where a few sector index short names collide exactly with a real fund's symbol.
- NSE cash rows split by instrument type, with three of those codes leaking investment trust rows that carry no marker of their own, so the allowlist is checked first there too. The bond types additionally need an ISIN check, because a row with no ISIN would otherwise collapse every such row onto one identity.

Identity extraction is the other quirk. Where a segment names ``symbol_ticker`` as its identity source, the real symbol has to be pulled out of a ticker like ``NSE:RELIANCE-EQ``; every other segment reads its declared column plainly. Applying the ticker pattern everywhere is a mistake with a silent and total failure mode: it never matches a BSE ticker, so an entire segment collapses onto a single identity of None, and therefore onto one instrument id.

The ONMIBOR redirect handles the one ordering interaction: the canonical order lists ``nse_fixed_income_futures`` before ``nse_fixed_income_index_futures``, so the broader rule claims the rate index futures first and the adapter moves them.

``broker_symbol`` carries ``symbol_details``, which is a human-readable description such as "RELIANCE 29 Sep 26 FUT", not a tradeable ticker. That is harmless for identity mapping, but any future order routing through Fyers must construct the API's own symbol format from the raw row rather than using this column.
"""

import re
from datetime import date as date_class

import pandas as pd

from stock_brokers.instruments.mapping.base import BrokerMappingAdapter
from stock_brokers.instruments.mapping.utilities.crossref import (
    equity_index_lookup,
    known_bse_etf_symbols,
    known_bse_investment_trust_symbols,
    known_nse_investment_trust_symbols,
)

TICKER_PATTERN = re.compile(r"^[A-Z]+:(.+)-[A-Z0-9]+$")

CLEAN_EQUITY_SUFFIXES = (
    "M",
    "MS",
    "MT",
    "P",
    "R",
    "X",
    "XT",
    "Y",
    "Z",
    "ZP",
)

BOND_SUFFIXES = (
    "F",
    "G",
)

BSE_INDEX_ALIASES = {
    "100": "BSE100",
    "100LARGECAPTMC": "LCTMCI",
    "150MIDCAP": "MID150",
    "200": "BSE200",
    "250LARGEMIDCAP": "LMI250",
    "250SMALLCAP": "SML250",
    "400MIDSMALLCAP": "MSL400",
    "500": "BSE500",
    "BASMTR": "COMDTY",
    "CARBONEX": "CARBON",
    "CD": "BSE CD",
    "CDGS": "CONDIS",
    "CG": "BSE CG",
    "DFRG": "DFRGRI",
    "DIVIDENDSTABILITY": "BSEDSI",
    "ENHANCEDVALUE": "BSEEVI",
    "FIN": "FINSER",
    "FMC": "BSEFMC",
    "GREENEX": "GREENX",
    "HC": "BSE HC",
    "INDIAMANUFACTURING": "MFG",
    "IPO": "BSEIPO",
    "IT": "BSE IT",
    "LOWVOLATILITY": "BSELVI",
    "MOMENTUM": "BSEMOI",
    "PRIVATEBANKS": "BSEPBI",
    "PSU": "BSEPSU",
    "QUALITY": "BSEQUI",
    "SENSEX50": "SNSX50",
    "SME IPO": "SMEIPO",
}

NSE_INDEX_ALIASES = {
    "NIFTY50": "NIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "NIFTYMIDCAP50": "NIFTYMCAP50",
    "NIFTYMIDCAP100": "NIFTY MID100 FREE",
    "NIFTYSMLCAP100": "NIFTY SMALLCAP 100",
    "NIFTYSMLCAP250": "NIFTY SMALLCAP 250",
    "NIFTYSMLCAP50": "NIFTY SMALLCAP 50",
    "NIFTYMIDSML400": "NIFTY MIDSMALLCAP 400",
    "NIFTY100LOWVOL30": "NIFTY100 LOW VOLATILITY 30",
    "NIFTY100EQLWGT": "NIFTY100 EQUAL WEIGHT",
    "NIFTYQUALITY30": "NIFTY100 QUALTY30",
}

EXCLUDED_NSE_INDEX_TICKER_PREFIXES = (
    "NSE:BHARATBOND-",
    "NSE:NIFTYGS",
)


def symbol_from_ticker(raw_ticker):
    """
    Pull the bare trading symbol out of a Fyers ticker such as ``NSE:RELIANCE-EQ``.

    Args:
        raw_ticker (str): The raw ticker value, or None.

    Returns:
        str | None: The symbol between the exchange prefix and the series suffix, or None when the ticker is absent or does not have that shape.
    """
    if not raw_ticker:
        return None
    match = TICKER_PATTERN.match(str(raw_ticker))
    if match is None:
        return None
    return match.group(1)


def normalize_index_name(name):
    """
    Reduce an index name to uppercase alphanumerics so that differently-spelled broker names collide.

    Args:
        name (str): The raw index name.

    Returns:
        str: The name with every non-alphanumeric character removed and uppercased.
    """
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


def isin_valid_non_fund(isin):
    """
    Check whether a row carries a usable ISIN that is not a fund-family ISIN.

    Args:
        isin (str | None): The raw ISIN value.

    Returns:
        bool: True when the ISIN is present and does not start with "INF".
    """
    if isin is None or pd.isna(isin) or str(isin).strip() == "":
        return False
    return not str(isin).startswith("INF")


class FyersMappingAdapter(BrokerMappingAdapter):
    """Mapping adapter for Fyers, covering 29 real segments plus the uncategorised buckets."""

    BROKER_NAME = "fyers"

    def run(self, mapping_date):
        """
        Map Fyers' raw rows for one date, precomputing the three allowlists and the NSE index lookup first.

        Args:
            mapping_date (datetime.date): The raw snapshot date to map.

        Returns:
            dict: The run summary, as described in BrokerMappingAdapter.run.
        """
        with self.engine.connect() as connection:
            self.nse_investment_trust_symbols = known_nse_investment_trust_symbols(connection, mapping_date)
            self.bse_investment_trust_symbols = known_bse_investment_trust_symbols(connection, mapping_date)
            self.bse_etf_symbols = known_bse_etf_symbols(connection, mapping_date)
            self.nse_index_master_lookup = equity_index_lookup(connection, mapping_date)


        return super().run(mapping_date)

    def classify(self, raw_row):
        """
        Classify a raw row, routing the two cash-market umbrellas in code and everything else through the rules.

        Args:
            raw_row (dict): One raw row from fyers.instruments.

        Returns:
            dict | None: The matched segment configuration, or None when no segment matches.
        """
        exchange = raw_row.get("exchange")
        segment = raw_row.get("segment")

        if exchange == "12":
            bse_segment_configuration = self._classify_bse(raw_row)
            if bse_segment_configuration is not None:
                return bse_segment_configuration
            if segment == "10" and raw_row.get("exchange_instrument_type") in ("0", "50"):
                return None
        elif exchange == "10" and segment == "10":
            return self._classify_nse_cash(raw_row)

        segment_configuration = super().classify(raw_row)
        if segment_configuration is None:
            return None
        if (
            segment_configuration["segment"] == "nse_fixed_income_futures"
            and raw_row.get("underlying_symbol") == "ONMIBOR"
        ):
            return self.segment_config("nse_fixed_income_index_futures")
        return segment_configuration

    def _classify_bse(self, raw_row):
        """
        Route a BSE row, checking the cross-broker allowlists before the instrument type split.

        Args:
            raw_row (dict): One raw row from fyers.instruments.

        Returns:
            dict | None: The matched segment configuration, or None to leave the row to the rules engine or to the uncategorised bucket.
        """
        instrument_type = raw_row.get("exchange_instrument_type")
        underlying = raw_row.get("underlying_symbol")

        if instrument_type != "10":
            if underlying in self.bse_etf_symbols:
                return self.segment_config("bse_exchange_traded_funds")
            if underlying in self.bse_investment_trust_symbols:
                return self.segment_config("bse_investment_trusts")

        if raw_row.get("segment") != "10":
            return None
        if instrument_type == "0":
            return self.segment_config("bse_equities")
        if instrument_type == "50":
            ticker = raw_row.get("symbol_ticker") or ""
            suffix = ticker.rsplit("-", 1)[-1] if "-" in ticker else ""
            isin = raw_row.get("isin")
            if suffix in BOND_SUFFIXES and isin_valid_non_fund(isin):
                return self.segment_config("bse_fixed_income")
            if suffix in CLEAN_EQUITY_SUFFIXES:
                return self.segment_config("bse_equities")
            if suffix == "B" and (isin is None or pd.isna(isin) or not str(isin).startswith("INF")):
                return self.segment_config("bse_equities")
            return None
        return None

    def _classify_nse_cash(self, raw_row):
        """
        Route an NSE cash-market row by instrument type, checking the investment trust allowlist first.

        Args:
            raw_row (dict): One raw row from fyers.instruments.

        Returns:
            dict | None: The matched segment configuration, or None when the row stays uncategorised.
        """
        instrument_type = raw_row.get("exchange_instrument_type")
        symbol = symbol_from_ticker(raw_row.get("symbol_ticker"))

        if instrument_type in ("0", "2", "4") and symbol in self.nse_investment_trust_symbols:
            return self.segment_config("nse_investment_trusts")
        if instrument_type in ("0", "3"):
            return self.segment_config("nse_equities")
        if instrument_type in ("2", "5", "6", "7"):
            if not isin_valid_non_fund(raw_row.get("isin")):
                return None
            return self.segment_config("nse_fixed_income")
        if instrument_type in ("4", "8"):
            return self.segment_config("nse_mutual_funds")
        if instrument_type == "9":
            return self.segment_config("nse_exchange_traded_funds")
        if instrument_type == "10":
            ticker = str(raw_row.get("symbol_ticker") or "")
            for excluded_prefix in EXCLUDED_NSE_INDEX_TICKER_PREFIXES:
                if ticker.startswith(excluded_prefix):
                    return None
            return self.segment_config("nse_equity_indices")
        return None

    def to_identity(self, raw_row, segment_configuration):
        """
        Build the unified identity fields, extracting the symbol from the ticker only where the segment declares that source.

        Args:
            raw_row (dict): One raw row from fyers.instruments.
            segment_configuration (dict): The segment configuration whose identity mapping applies.

        Returns:
            dict: Identity fields, as described in BrokerMappingAdapter.to_identity.

        Raises:
            ValueError: If an expiry value is numeric with no explicit transform.
        """
        identity = super().to_identity(raw_row, segment_configuration)
        segment = segment_configuration["segment"]

        if segment_configuration["identity"].get("symbol") == "symbol_ticker":
            identity["symbol"] = symbol_from_ticker(raw_row.get("symbol_ticker"))

        if segment == "bse_equity_indices" and identity.get("symbol"):
            identity["symbol"] = BSE_INDEX_ALIASES.get(identity["symbol"], identity["symbol"])
        elif segment == "nse_equity_indices" and identity.get("symbol"):
            normalized = normalize_index_name(identity["symbol"])
            if normalized in NSE_INDEX_ALIASES:
                identity["symbol"] = NSE_INDEX_ALIASES[normalized]
            elif normalized in self.nse_index_master_lookup:
                identity["symbol"] = self.nse_index_master_lookup[normalized]
        return identity

    def uncategorised_exchange(self, raw_row):
        """
        Determine the canonical exchange for an unmatched Fyers row from its numeric exchange code.

        Args:
            raw_row (dict): One raw row from fyers.instruments.

        Returns:
            str | None: "nse", "bse", or "mcx", or None for any other code.
        """
        exchange_code = raw_row.get("exchange")
        if exchange_code == "10":
            return "nse"
        if exchange_code == "12":
            return "bse"
        if exchange_code == "11":
            return "mcx"
        return None


if __name__ == "__main__":
    import argparse

    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--date", type=str, default=None)
    arguments = argument_parser.parse_args()
    FyersMappingAdapter().run(date_class.fromisoformat(arguments.date) if arguments.date else date_class.today())
