"""
IND Money mapping adapter.

IND Money's file has three peculiarities that the rules engine cannot express on its own.

The first is that it has no index marker at all. An index row is identified by exclusion: its ``segment`` column holds the index's own name ("NIFTY 50", "BANK NIFTY") rather than one of the two real segment codes, E for the cash market and D for derivatives. So index classification is "anything that is neither", with the government securities index names excluded, and the name is then resolved to the canonical symbol through an alias table and, on the NSE side, the day's already-written master rows.

The second is that neither derivative segment has an underlying symbol column. It is extracted from the trading symbol, which is patterned as ``360ONE-Nov2026-1000-CE`` on NSE and ``BANKEX-24Sep2026-57200-CE`` on BSE.

The third is the expiry format, ``MM/DD/YYYY HH:MM``, which is month-first and needs an explicit parse.

This project's IND Money download captures an ``isin`` column, but only from 2026-09-02 onwards: every earlier snapshot has it empty. So the ISIN is read from the row where the row has one, and resolved through the cross-broker security identifier map where it does not. Both fixed income identity and fund detection in the equity segments go through that one resolution, which makes the adapter behave the same way on every stored date rather than only on the recent ones. The two exchange traded fund allowlists are still needed, because an ISIN says that a row is a fund but not whether it is a listed exchange traded fund or a mutual fund scheme.
"""

import re
from datetime import date as date_class

import pandas as pd

from stock_brokers.instruments.mapping.base import BrokerMappingAdapter
from stock_brokers.instruments.mapping.utilities.crossref import (
    equity_index_lookup,
    known_bse_etf_symbols,
    known_nse_etf_symbols,
    security_id_to_isin,
)

FUTURES_UNDERLYING_PATTERN = re.compile(r"^(.+)-\d{0,2}[A-Za-z]{3}\d{4}-FUT$")
OPTIONS_UNDERLYING_PATTERN = re.compile(r"^(.+)-\d{0,2}[A-Za-z]{3}\d{4}-[\d.]+-(?:CE|PE)$")

NSE_FUTURES_SEGMENTS = (
    "nse_equity_futures",
    "nse_equity_index_futures",
)

NSE_OPTIONS_SEGMENTS = (
    "nse_equity_options",
    "nse_equity_index_options",
)

REAL_SEGMENT_CODES = (
    "D",
    "E",
)

NSE_GOVERNMENT_SECURITIES_INDEX_NAMES = (
    "Nifty 8-13 G-Sec",
    "Nifty 10 B-G Sec",
    "Nifty10 BG-Sec-C",
    "Nifty GS 11 15Yr",
    "Nifty GS 15YrPlu",
    "Nifty GS 4 8Yr",
    "Nifty GS Compsit",
)

NSE_ETF_SERIES = (
    "EQ",
    "SM",
    "BE",
    "ST",
    "BZ",
    "SZ",
    "E1",
    "IT",
    "W1",
)

FIXED_INCOME_TYPES = (
    "GB",
    "TB",
    "DBT",
    "DEB",
    "CB",
    "PTC",
)

NSE_BOND_SERIES = (
    "GB",
    "GS",
    "SG",
    "TB",
)

NSE_BOND_SERIES_PATTERN = re.compile(r"^[NY]")

NSE_INDEX_ALIASES = {
    "NIFTY50": "NIFTY",
    "NFTY500M502525": "NIFTY500 MULTICAP",
    "NIFTY100LIQUID15": "NIFTY100 LIQ 15",
    "NIFTY50EQWGHT": "NIFTY50 EQL WGT",
    "NIFTYALPHALV30": "NIFTY ALPHALOWVOL",
    "NIFTYCONSUMERDURABLES": "NIFTY CONSR DURBL",
    "NIFTYDIVOPP50": "NIFTY DIV OPPS 50",
    "NIFTYFINANCIAL": "FINNIFTY",
    "NIFTYGROWSEC15": "NIFTY GROWSECT 15",
    "NIFTYINDIACONSUMPTION": "NIFTY CONSUMPTION",
    "NIFTYINDIADIG": "NIFTY IND DIGITAL",
    "NIFTYLARGEMIDCAP250": "NIFTY LARGEMID250",
    "NIFTYMICROCP250": "NIFTY MICROCAP250",
    "NIFTYMIDCAP100": "NIFTY MID100 FREE",
    "NIFTYMIDCAP50": "NIFTYMCAP50",
    "NIFTYMIDCAPLIQUID15": "NIFTY MID LIQ 15",
    "NIFTYMIDCAPSEL": "MIDCPNIFTY",
    "NIFTYMIDCAP150Q": "NIFTY M150 QLTY50",
    "NIFTYNEXT50": "NIFTYNXT50",
    "NIFTYOILGAS": "NIFTY OIL AND GAS",
    "NIFTYPRIVATEBANK": "NIFTY PVT BANK",
    "NIFTYSERVICESSECTOR": "NIFTY SERV SECTOR",
    "NIFTYSMALL100": "NIFTY SMALLCAP 100",
    "NIFTYTOTALMAR": "NIFTY TOTAL MKT",
    "NIFTY100ESGSEC": "NIFTY100ESGSECLDR",
    "NIFTY100EQWEIG": "NIFTY100 EQUAL WEIGHT",
    "NIFTY100QUALITY": "NIFTY100 QUALTY30",
    "NIFTY200MOMEN30": "NIFTY200MOMENTM30",
    "NIFTY200QUAL30": "NIFTY200 QUALTY30",
}

BSE_INDEX_ALIASES = {
    "BSE 100": "BSE100",
    "BSE 200": "BSE200",
    "BSE 500": "BSE500",
    "BSE Auto": "AUTO",
    "BSE Consumer Discretionary": "CONDIS",
    "BSE Dollex 100": "DOL100",
    "BSE Dollex 200": "DOL200",
    "BSE Dollex 30": "DOL30",
    "BSE FMCG Sector": "BSEFMC",
    "BSE Focused IT": "FOCIT",
    "BSE Greenex": "GREENX",
    "BSE Healthcare": "BSE HC",
    "BSE IPO": "BSEIPO",
    "BSE IT Sector": "BSE IT",
    "BSE MFG": "MFG",
    "BSE Mid-Cap": "MIDCAP",
    "BSE SME IPO": "SMEIPO",
    "BSE Small-Cap": "SMLCAP",
    "BSE Tech": "TECK",
    "DFRGRI Indices": "DFRGRI",
    "S&P BSE 100 ESG": "ESG100",
    "S&P BSE 100 LargeCap TMC": "LCTMCI",
    "S&P BSE 150 MidCap": "MID150",
    "S&P BSE 250 LargeMidCap": "LMI250",
    "S&P BSE 250 SmallCap": "SML250",
    "S&P BSE 400 MidSmallCap": "MSL400",
    "S&P BSE AllCap": "ALLCAP",
    "S&P BSE Bharat 22": "BHRT22",
    "S&P BSE CARBONEX": "CARBON",
    "S&P BSE CPSE": "CPSE",
    "S&P BSE Capital Goods": "BSE CG",
    "S&P BSE Commodities": "COMDTY",
    "S&P BSE Consumer Durables": "BSE CD",
    "S&P BSE Dividend Stability": "BSEDSI",
    "S&P BSE Enhanced Value": "BSEEVI",
    "S&P BSE Energy": "ENERGY",
    "S&P BSE Fin. Ser": "FINSER",
    "S&P BSE Indus.": "INDSTR",
    "S&P BSE Infra.": "INFRA",
    "S&P BSE Largecap": "LRGCAP",
    "S&P BSE Low Volatility": "BSELVI",
    "S&P BSE Metal": "METAL",
    "S&P BSE MidCap Select": "MIDSEL",
    "S&P BSE Momentum": "BSEMOI",
    "S&P BSE OIL & GAS": "OILGAS",
    "S&P BSE POWER": "POWER",
    "S&P BSE PSU": "BSEPSU",
    "S&P BSE Private Banks": "BSEPBI",
    "S&P BSE Quality": "BSEQUI",
    "S&P BSE Realty": "REALTY",
    "S&P BSE SEN. N50": "SNXT50",
    "S&P BSE SENSEX 50": "SNSX50",
    "S&P BSE SmallCap Select": "SMLSEL",
    "S&P BSE Telecom.": "TELCOM",
    "S&P BSE Utilities": "UTILS",
}


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
        isin (str | None): The raw ISIN value from an IND Money row.

    Returns:
        bool: True when the ISIN is present and does not start with "INF".
    """
    if isin is None or pd.isna(isin) or str(isin).strip() == "":
        return False
    return not str(isin).startswith("INF")


def isin_is_fund(isin):
    """
    Check whether an ISIN belongs to the fund family, which India marks with an INF prefix.

    Args:
        isin (str | None): The raw ISIN value from an IND Money row.

    Returns:
        bool: True when the ISIN is present and starts with "INF".
    """
    if isin is None or pd.isna(isin):
        return False
    return str(isin).startswith("INF")


class IndMoneyMappingAdapter(BrokerMappingAdapter):
    """Mapping adapter for IND Money, covering 17 real segments plus the uncategorised buckets."""

    BROKER_NAME = "indmoney"

    def run(self, mapping_date):
        """
        Map IND Money's raw rows for one date, precomputing the two exchange traded fund allowlists, the shared security identifier map and the NSE index lookup first.

        Args:
            mapping_date (datetime.date): The raw snapshot date to map.

        Returns:
            dict: The run summary, as described in BrokerMappingAdapter.run.
        """
        with self.engine.connect() as connection:
            self.nse_etf_symbols = known_nse_etf_symbols(connection, mapping_date)
            self.bse_etf_symbols = known_bse_etf_symbols(connection, mapping_date)
            self.isin_by_security_id = security_id_to_isin(connection, mapping_date)
            self.nse_index_master_lookup = equity_index_lookup(connection, mapping_date)


        return super().run(mapping_date)

    def _field(self, raw_row, specification):
        """
        Read one raw column value, adding IND Money's two broker-local transforms to the shared ones.

        Args:
            raw_row (dict): One raw row from indmoney.instruments.
            specification: A bare column name, or a {column, transform} pair.

        Returns:
            The resolved value.
        """
        if isinstance(specification, dict):
            transform = specification.get("transform")
            if transform == "underlying_before_first_hyphen":
                value = raw_row.get(specification["column"])
                if not value:
                    return None
                return str(value).split("-")[0]
            if transform == "month_day_year_time":
                value = raw_row.get(specification["column"])
                if not value or pd.isna(value):
                    return None
                try:
                    return pd.to_datetime(value, format="%m/%d/%Y %H:%M").date()
                except (ValueError, TypeError):
                    return None
        return super()._field(raw_row, specification)

    def resolved_isin(self, raw_row):
        """
        Read a row's ISIN, falling back to the cross-broker security identifier map where the row carries none.

        IND Money only began publishing an ISIN column on 2026-09-02, so every earlier snapshot needs the fallback. Without it the bond segments cannot be identified at all on those dates and their rows land in the uncategorised buckets.

        Args:
            raw_row (dict): One raw row from indmoney.instruments.

        Returns:
            str | None: The ISIN, or None when neither the row nor the shared map has one.
        """
        isin = raw_row.get("isin")
        if isin is not None and not pd.isna(isin) and str(isin).strip() != "":
            return str(isin).strip()
        return self.isin_by_security_id.get(str(raw_row.get("security_id")))

    def classify(self, raw_row):
        """
        Classify a raw row, running the rules first and then the three code-driven checks for the segments no rule can express.

        Args:
            raw_row (dict): One raw row from indmoney.instruments.

        Returns:
            dict | None: The matched segment configuration, or None when no segment matches.
        """
        segment_configuration = super().classify(raw_row)
        if segment_configuration is None:
            segment_configuration = self._classify_index(raw_row)
        if segment_configuration is None:
            segment_configuration = self._classify_exchange_traded_fund(raw_row)
        if segment_configuration is None:
            segment_configuration = self._classify_fixed_income(raw_row)
        if segment_configuration is None:
            return None

        segment = segment_configuration["segment"]
        if segment == "nse_equities":
            if raw_row.get("trading_symbol") in self.nse_etf_symbols:
                return self.segment_config("nse_exchange_traded_funds")
            if isin_is_fund(self.resolved_isin(raw_row)):
                return None
        if segment == "bse_equities":
            if raw_row.get("trading_symbol") in self.bse_etf_symbols:
                return self.segment_config("bse_exchange_traded_funds")
            if isin_is_fund(self.resolved_isin(raw_row)):
                return None
        if segment == "nse_mutual_funds" and raw_row.get("trading_symbol") in self.nse_etf_symbols:
            return None
        return segment_configuration

    def _classify_index(self, raw_row):
        """
        Classify an index row, which IND Money marks only by putting the index's own name in its segment column.

        Args:
            raw_row (dict): One raw row from indmoney.instruments.

        Returns:
            dict | None: The index segment configuration, or None when the row is not an index.
        """
        exchange = raw_row.get("exch")
        segment = raw_row.get("segment")
        if segment in REAL_SEGMENT_CODES:
            return None
        if exchange == "BSE":
            return self.segment_config("bse_equity_indices")
        if exchange == "NSE" and segment not in NSE_GOVERNMENT_SECURITIES_INDEX_NAMES:
            return self.segment_config("nse_equity_indices")
        return None

    def _classify_exchange_traded_fund(self, raw_row):
        """
        Classify a row the other brokers independently confirm to be an exchange traded fund.

        Args:
            raw_row (dict): One raw row from indmoney.instruments.

        Returns:
            dict | None: The exchange traded fund segment configuration, or None.
        """
        exchange = raw_row.get("exch")
        symbol = raw_row.get("trading_symbol")
        instrument_type = raw_row.get("sem_exch_instrument_type")
        if exchange == "BSE" and instrument_type in ("MF", "ETF") and symbol in self.bse_etf_symbols:
            return self.segment_config("bse_exchange_traded_funds")
        if (
            exchange == "NSE"
            and raw_row.get("segment") == "E"
            and raw_row.get("series") in NSE_ETF_SERIES
            and symbol in self.nse_etf_symbols
        ):
            return self.segment_config("nse_exchange_traded_funds")
        return None

    def _classify_fixed_income(self, raw_row):
        """
        Classify a bond row by instrument type and series, requiring a real non-fund ISIN.

        The identity for both fixed income segments is the ISIN itself, so a row without a usable one cannot be identified and is left for the uncategorised bucket.

        Args:
            raw_row (dict): One raw row from indmoney.instruments.

        Returns:
            dict | None: The fixed income segment configuration, or None.
        """
        if raw_row.get("segment") != "E" or raw_row.get("instrument_name") != "EQUITY":
            return None
        if not isin_valid_non_fund(self.resolved_isin(raw_row)):
            return None

        exchange = raw_row.get("exch")
        instrument_type = raw_row.get("sem_exch_instrument_type")
        series = raw_row.get("series")

        if exchange == "BSE":
            is_bond = (
                instrument_type in FIXED_INCOME_TYPES
                or (instrument_type == "Other" and series in ("F", "G"))
                or (instrument_type == "PN" and series == "F")
            )
            if is_bond:
                return self.segment_config("bse_fixed_income")
        if exchange == "NSE":
            series_is_blank = series is None or pd.isna(series) or str(series).strip() == ""
            is_bond = instrument_type in FIXED_INCOME_TYPES or (
                instrument_type == "Other"
                and (
                    series in NSE_BOND_SERIES
                    or series_is_blank
                    or (isinstance(series, str) and NSE_BOND_SERIES_PATTERN.match(series))
                )
            )
            if is_bond:
                return self.segment_config("nse_fixed_income")
        return None

    def to_identity(self, raw_row, segment_configuration):
        """
        Build the unified identity fields, extracting derivative underlyings from the trading symbol and resolving index names.

        Args:
            raw_row (dict): One raw row from indmoney.instruments.
            segment_configuration (dict): The segment configuration whose identity mapping applies.

        Returns:
            dict: Identity fields, as described in BrokerMappingAdapter.to_identity.

        Raises:
            ValueError: If an expiry value is numeric with no explicit transform.
        """
        segment = segment_configuration["segment"]
        if segment in ("nse_fixed_income", "bse_fixed_income"):
            return {
                "symbol": self.resolved_isin(raw_row),
            }

        identity = super().to_identity(raw_row, segment_configuration)

        if segment in NSE_FUTURES_SEGMENTS or segment in NSE_OPTIONS_SEGMENTS:
            if segment in NSE_FUTURES_SEGMENTS:
                pattern = FUTURES_UNDERLYING_PATTERN
            else:
                pattern = OPTIONS_UNDERLYING_PATTERN
            match = pattern.match(str(raw_row.get("trading_symbol") or ""))
            identity["underlying_symbol"] = match.group(1) if match else None
            return identity

        if segment == "bse_equity_indices":
            raw_name = raw_row.get("segment")
            identity["symbol"] = BSE_INDEX_ALIASES.get(raw_name, raw_name)
            return identity

        if segment == "nse_equity_indices":
            raw_name = raw_row.get("segment")
            normalized = normalize_index_name(raw_name)
            if normalized in NSE_INDEX_ALIASES:
                identity["symbol"] = NSE_INDEX_ALIASES[normalized]
            elif normalized in self.nse_index_master_lookup:
                identity["symbol"] = self.nse_index_master_lookup[normalized]
            else:
                identity["symbol"] = raw_name
            return identity

        return identity

    def uncategorised_exchange(self, raw_row):
        """
        Determine the canonical exchange for an unmatched IND Money row from its exchange column.

        Args:
            raw_row (dict): One raw row from indmoney.instruments.

        Returns:
            str | None: "nse" or "bse", or None for any other value.
        """
        exchange_identifier = raw_row.get("exch")
        if exchange_identifier == "NSE":
            return "nse"
        if exchange_identifier == "BSE":
            return "bse"
        return None


if __name__ == "__main__":
    import argparse

    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--date", type=str, default=None)
    arguments = argument_parser.parse_args()
    IndMoneyMappingAdapter().run(date_class.fromisoformat(arguments.date) if arguments.date else date_class.today())
