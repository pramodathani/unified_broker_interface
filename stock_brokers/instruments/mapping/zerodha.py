"""
Zerodha mapping adapter.

Zerodha lumps almost everything under one flat instrument type per exchange, with no discriminating column of its own. NSE "EQ" covers equities, exchange traded funds, mutual fund plans, investment trusts, and corporate bonds together; BSE "EQ" the same minus the mutual funds; the currency segment covers currency pairs, government bond derivatives, and the overnight rate index together; and the derivative exchanges mix stock and index contracts.

Nothing here is a plain equality match, so this adapter classifies every row itself and the rules file carries no rules at all — only the identity and broker field mappings, which the base class still reads. Classification dispatches on the exchange, segment, and instrument type together, so each row lands in exactly one place.

The NSE flat bucket is decided by the trading symbol's suffix, taken as the last hyphen-separated part rather than the second, since a base symbol can itself contain a hyphen. The BSE flat bucket has no suffix convention and is decided by a sequence of name and symbol heuristics, with the cross-broker fund allowlist checked first: the fixed income heuristics are broad enough to claim a fund ticker otherwise.

Zerodha carries no ISIN column, so both fixed income segments take their identity from the shared security identifier map, keyed on this broker's own exchange token, which sits in the same exchange-assigned numbering the ISIN-bearing brokers use.
"""

import re
from datetime import date as date_class

import pandas as pd

from stock_brokers.instruments.mapping.base import BrokerMappingAdapter
from stock_brokers.instruments.mapping.utilities.crossref import (
    equity_index_lookup,
    known_bse_etf_symbols,
    known_bse_fixed_income_symbols,
    known_bse_fund_symbols,
    known_bse_investment_trust_symbols,
    known_nse_etf_symbols,
    known_nse_fund_symbols,
    security_id_to_isin,
)

INDEX_UNDERLYINGS = (
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTY",
    "NIFTYFPI",
    "NIFTYNXT50",
)

CURRENCY_NAMES = (
    "EURINR",
    "EURUSD",
    "GBPINR",
    "GBPUSD",
    "JPYINR",
    "USDINR",
    "USDJPY",
)

MCX_INDEX_NAMES = (
    "MCXBULLDEX",
    "MCXMETLDEX",
)

NSE_BOND_SUFFIXES = (
    "SG",
    "TB",
    "GB",
    "GS",
)

NSE_BLANK_NAME_NON_BOND_SUFFIXES = (
    "SF",
    "RL",
    "SG",
    "TB",
    "GB",
    "GS",
)

EXCLUDED_NSE_INDEX_SYMBOLS = (
    "HANGSENG BEES-NAV",
)

EXCLUDED_NSE_INDEX_PREFIXES = (
    "BHARATBOND-",
    "NIFTY GS",
)

SERIES_SUFFIX_PATTERN = re.compile(r"-(?:SM|BE|ST|BZ|SZ|E1|IT|W1)$")
TRUST_SUFFIX_PATTERN = re.compile(r"-(?:IV|RR)$")
MUTUAL_FUND_SUFFIX_PATTERN = re.compile(r"-SF$")
BSE_FIXED_INCOME_NAME_PATTERN = re.compile(r"goi|govt|sovereign gold", re.IGNORECASE)
EXCHANGE_TRADED_FUND_NAME_PATTERN = re.compile(r"etf|exchange traded fund", re.IGNORECASE)

NSE_INDEX_ALIASES = {
    "NIFTY50": "NIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "NIFTYFINSERVICE": "FINNIFTY",
    "NIFTYMIDSELECT": "MIDCPNIFTY",
    "NIFTYMIDCAP100": "NIFTY MID100 FREE",
    "NIFTYMIDCAP50": "NIFTYMCAP50",
    "NIFTYMIDSML400": "NIFTY MIDSMALLCAP 400",
    "NIFTYNEXT50": "NIFTYNXT50",
    "NIFTYSMLCAP100": "NIFTY SMALLCAP 100",
    "NIFTYSMLCAP250": "NIFTY SMALLCAP 250",
    "NIFTYSMLCAP50": "NIFTY SMALLCAP 50",
    "NIFTY100ENHANCEDESG": "Nifty100 Enh ESG",
    "NIFTY100EQLWGT": "NIFTY100 EQUAL WEIGHT",
    "NIFTY100LOWVOL30": "NIFTY100 LOW VOLATILITY 30",
    "NIFTY500EQUALWEIGHT": "Nifty500 EW",
}

BSE_INDEX_ALIASES = {
    "BASMTR": "COMDTY",
    "BSE 1000": "BS1000",
    "BSE 200 EQUAL WEIGHT": "200EQW",
    "BSE CAPITAL MKTS & INSURANCE": "CAPINS",
    "BSE FOCUSED IT": "FOCIT",
    "BSE FOCUSED MIDCAP": "FOCMID",
    "BSE INDIA 150": "IND150",
    "BSE INDIA SECT LEADER": "INSLDR",
    "BSE POWER & ENERGY": "POWENE",
    "BSE PSU BANK": "PSUBNK",
    "BSE SENSEX SIXTY": "SNSX60",
    "BSE SENSEX SIXTY 65:35": "SS6535",
    "BSE SERVICES": "BSESER",
    "BSE SME IPO": "SMEIPO",
    "CDGS": "CONDIS",
    "ENERGY INDEX": "ENERGY",
    "FINANCIAL SERVICES": "FINSER",
    "INFRA INDEX": "INFRA",
    "METAL INDEX": "METAL",
    "MID150 INDEX": "MID150",
    "MIDCAP INDEX": "MIDCAP",
    "SENSEX NEXT 30": "SNXN30",
}

MCX_INDEX_ALIASES = {
    "MCXENERGY": "MCXENRGDEX",
}

MISLABELLED_COMMODITY_NAME = "ADITYA BIRLA SUN LIFE SILVER ETF"

FIXED_INCOME_SEGMENTS = (
    "nse_fixed_income",
    "bse_fixed_income",
)

BROKER_SYMBOL_FALLBACK_SEGMENTS = (
    "nse_mutual_funds",
    "nse_fixed_income",
    "bse_fixed_income",
    "bse_exchange_traded_funds",
)


def is_blank(value):
    """
    Check whether a raw value is absent or empty, in any of the forms the raw tables produce.

    Args:
        value (str | float | None): One raw column value.

    Returns:
        bool: True when the value is None, an empty string, or a pandas missing value.
    """
    if value is None or value == "":
        return True
    return isinstance(value, float) and pd.isna(value)


def normalize_index_name(name):
    """
    Reduce an index name to uppercase alphanumerics so that differently-spelled broker names collide.

    Args:
        name (str): The raw index name.

    Returns:
        str: The name with every non-alphanumeric character removed and uppercased.
    """
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


class ZerodhaMappingAdapter(BrokerMappingAdapter):
    """Mapping adapter for Zerodha, covering 30 real segments plus the uncategorised buckets."""

    BROKER_NAME = "zerodha"

    def run(self, mapping_date):
        """
        Map Zerodha's raw rows for one date, precomputing the six allowlists, the ISIN map, and the index lookup first.

        Args:
            mapping_date (datetime.date): The raw snapshot date to map.

        Returns:
            dict: The run summary, as described in BrokerMappingAdapter.run.
        """
        with self.engine.connect() as connection:
            self.nse_fund_symbols = known_nse_fund_symbols(connection, mapping_date)
            self.nse_etf_symbols = known_nse_etf_symbols(connection, mapping_date)
            self.bse_fund_symbols = known_bse_fund_symbols(connection, mapping_date)
            self.bse_trust_symbols = known_bse_investment_trust_symbols(connection, mapping_date)
            self.bse_fixed_income_symbols = known_bse_fixed_income_symbols(connection, mapping_date)
            self.bse_etf_symbols = known_bse_etf_symbols(connection, mapping_date)
            self.isin_by_token = security_id_to_isin(connection, mapping_date)
            self.nse_index_master_lookup = equity_index_lookup(connection, mapping_date)


        return super().run(mapping_date)

    def classify(self, raw_row):
        """
        Classify a raw row, then check that a bond row can actually be identified.

        Both fixed income segments take their identity from the shared security identifier map, so a row that map cannot resolve has no identity to be written under. It is left for the uncategorised bucket rather than dropped, which keeps the run's coverage reconciling: on a date where only this broker was downloaded, the map is empty and every bond row lands there.

        Args:
            raw_row (dict): One raw row from zerodha.instruments.

        Returns:
            dict | None: The matched segment configuration, or None when no segment matches or a bond row cannot be identified.
        """
        segment_configuration = self._classify_by_exchange(raw_row)
        if segment_configuration is None:
            return None
        if segment_configuration["segment"] in FIXED_INCOME_SEGMENTS:
            if str(raw_row.get("exchange_token")) not in self.isin_by_token:
                return None
        return segment_configuration

    def _classify_by_exchange(self, raw_row):
        """
        Dispatch a raw row on its exchange, segment, and instrument type together.

        Args:
            raw_row (dict): One raw row from zerodha.instruments.

        Returns:
            dict | None: The matched segment configuration, or None when no segment matches.
        """
        exchange = raw_row.get("exchange")
        segment = raw_row.get("segment")
        instrument_type = raw_row.get("instrument_type")

        if exchange == "NSE" and segment == "NSE" and instrument_type == "EQ":
            return self._classify_nse_flat(raw_row)
        if exchange == "NSE" and segment == "INDICES":
            return self._classify_nse_index(raw_row)
        if exchange == "NFO":
            return self._classify_nse_derivatives(raw_row, instrument_type)
        if exchange == "BSE" and segment == "BSE" and instrument_type == "EQ":
            return self._classify_bse_flat(raw_row)
        if exchange == "BSE" and segment == "INDICES":
            return self.segment_config("bse_equity_indices")
        if exchange == "BFO":
            return self._classify_bse_derivatives(instrument_type)
        if exchange == "MCX":
            return self._classify_mcx(raw_row, segment)
        if exchange == "NCO":
            return self._classify_nse_commodities(instrument_type)
        if exchange == "CDS":
            return self._classify_currency_derivatives(raw_row, instrument_type)
        return None

    def _classify_nse_flat(self, raw_row):
        """
        Route an NSE cash-market row, which shares one instrument type across five segments, by its trading symbol suffix.

        Args:
            raw_row (dict): One raw row from zerodha.instruments.

        Returns:
            dict | None: The matched segment configuration, or None.
        """
        trading_symbol = raw_row.get("tradingsymbol") or ""
        name = raw_row.get("name")
        name_is_blank = is_blank(name)
        parts = trading_symbol.split("-")
        suffix = parts[-1] if len(parts) > 1 else None

        if suffix in NSE_BOND_SUFFIXES:
            return self.segment_config("nse_fixed_income")
        if name_is_blank and "-" in trading_symbol and suffix not in NSE_BLANK_NAME_NON_BOND_SUFFIXES:
            return self.segment_config("nse_fixed_income")
        if suffix in ("IV", "RR"):
            return self.segment_config("nse_investment_trusts")
        if suffix == "SF":
            return self.segment_config("nse_mutual_funds")
        if name_is_blank:
            return None
        if "INAV" in trading_symbol:
            return None
        if trading_symbol in self.nse_etf_symbols:
            return self.segment_config("nse_exchange_traded_funds")
        if "etf" in str(name).lower():
            return None
        if trading_symbol in self.nse_fund_symbols:
            return None
        return self.segment_config("nse_equities")

    def _classify_nse_index(self, raw_row):
        """
        Route an NSE index row, excluding the bond-shaped and foreign reference rows that are not equity indices.

        Args:
            raw_row (dict): One raw row from zerodha.instruments.

        Returns:
            dict | None: The index segment configuration, or None.
        """
        trading_symbol = raw_row.get("tradingsymbol") or ""
        if trading_symbol in EXCLUDED_NSE_INDEX_SYMBOLS:
            return None
        for excluded_prefix in EXCLUDED_NSE_INDEX_PREFIXES:
            if trading_symbol.startswith(excluded_prefix):
                return None
        return self.segment_config("nse_equity_indices")

    def _classify_bse_flat(self, raw_row):
        """
        Route a BSE cash-market row, which has no suffix convention, by name and symbol heuristics.

        The cross-broker fund check runs first: the fixed income heuristics below are broad — a blank name with any digit in the symbol is one of them — and would otherwise claim a fund ticker such as "GSEC10ADD".

        Args:
            raw_row (dict): One raw row from zerodha.instruments.

        Returns:
            dict | None: The matched segment configuration, or None.
        """
        trading_symbol = raw_row.get("tradingsymbol") or ""
        name = raw_row.get("name")
        name_is_blank = is_blank(name)

        is_exchange_traded_fund = trading_symbol in self.bse_etf_symbols
        if not name_is_blank and EXCHANGE_TRADED_FUND_NAME_PATTERN.search(str(name)):
            is_exchange_traded_fund = True
        if is_exchange_traded_fund:
            return self.segment_config("bse_exchange_traded_funds")

        if self._is_bse_fixed_income(raw_row, trading_symbol, name, name_is_blank):
            return self.segment_config("bse_fixed_income")

        if trading_symbol in self.bse_trust_symbols:
            return self.segment_config("bse_investment_trusts")
        if name_is_blank:
            return None
        if trading_symbol in self.bse_fund_symbols or trading_symbol in self.bse_fixed_income_symbols:
            return None
        return self.segment_config("bse_equities")

    def _is_bse_fixed_income(self, raw_row, trading_symbol, name, name_is_blank):
        """
        Check the heuristics that mark a BSE cash-market row as a bond.

        Args:
            raw_row (dict): One raw row from zerodha.instruments.
            trading_symbol (str): The row's trading symbol.
            name: The row's name column.
            name_is_blank (bool): Whether the name is absent.

        Returns:
            bool: True when the row looks like a bond.
        """
        if not name_is_blank:
            if BSE_FIXED_INCOME_NAME_PATTERN.search(str(name)):
                return True
            if name == trading_symbol:
                return True
            if "SDL" in str(name).upper():
                return True
        if trading_symbol.startswith("SGB") and not name_is_blank:
            return True
        if name_is_blank and re.search(r"[0-9]", trading_symbol):
            return True
        return "SDL" in trading_symbol.upper()

    def classify_extra(self, raw_row):
        """
        Return the equity membership a BSE cash-market row also has when it meets the equity criteria in its own right.

        A BSE row can meet more than one segment's criteria, so one row can belong to two segments at once. Of the Zerodha BSE rows whose name equals their trading symbol — one of the bond heuristics — a substantial minority are also genuinely equities. This re-checks the equity criteria independently of what the primary classification chose.

        Args:
            raw_row (dict): One raw row from zerodha.instruments.

        Returns:
            list[dict]: The equity segment configuration, or an empty list.
        """
        if raw_row.get("exchange") != "BSE" or raw_row.get("segment") != "BSE":
            return []
        if raw_row.get("instrument_type") != "EQ":
            return []
        trading_symbol = raw_row.get("tradingsymbol") or ""
        name = raw_row.get("name")
        if is_blank(name):
            return []
        if EXCHANGE_TRADED_FUND_NAME_PATTERN.search(str(name)) or trading_symbol in self.bse_etf_symbols:
            return []
        if trading_symbol in self.bse_trust_symbols:
            return []
        if trading_symbol in self.bse_fund_symbols or trading_symbol in self.bse_fixed_income_symbols:
            return []
        return [
            self.segment_config("bse_equities"),
        ]

    def _classify_nse_derivatives(self, raw_row, instrument_type):
        """
        Route an NSE derivative row, splitting stock from index contracts by the underlying name.

        Args:
            raw_row (dict): One raw row from zerodha.instruments.
            instrument_type (str): The row's instrument type.

        Returns:
            dict | None: The matched segment configuration, or None.
        """
        is_index = raw_row.get("name") in INDEX_UNDERLYINGS
        if instrument_type == "FUT":
            if is_index:
                return self.segment_config("nse_equity_index_futures")
            return self.segment_config("nse_equity_futures")
        if instrument_type in ("CE", "PE"):
            if is_index:
                return self.segment_config("nse_equity_index_options")
            return self.segment_config("nse_equity_options")
        return None

    def _classify_bse_derivatives(self, instrument_type):
        """
        Route a BSE derivative row, which this broker's file carries for index contracts only.

        Args:
            instrument_type (str): The row's instrument type.

        Returns:
            dict | None: The matched segment configuration, or None.
        """
        if instrument_type == "FUT":
            return self.segment_config("bse_equity_index_futures")
        if instrument_type in ("CE", "PE"):
            return self.segment_config("bse_equity_index_options")
        return None

    def _classify_mcx(self, raw_row, segment):
        """
        Route an MCX row, splitting commodity from commodity index contracts by the underlying name.

        Args:
            raw_row (dict): One raw row from zerodha.instruments.
            segment (str): The row's segment column.

        Returns:
            dict | None: The matched segment configuration, or None.
        """
        if segment == "INDICES":
            return self.segment_config("mcx_commodity_indices")
        is_index = raw_row.get("name") in MCX_INDEX_NAMES
        if segment == "MCX-FUT":
            if is_index:
                return self.segment_config("mcx_commodity_index_futures")
            return self.segment_config("mcx_commodity_futures")
        if segment == "MCX-OPT":
            if is_index:
                return self.segment_config("mcx_commodity_index_options")
            return self.segment_config("mcx_commodity_options")
        return None

    def _classify_nse_commodities(self, instrument_type):
        """
        Route an NSE commodity row, a segment only this broker's file carries.

        Args:
            instrument_type (str): The row's instrument type.

        Returns:
            dict | None: The matched segment configuration, or None.
        """
        if instrument_type == "EQ":
            return self.segment_config("nse_commodities")
        if instrument_type == "FUT":
            return self.segment_config("nse_commodity_futures")
        if instrument_type in ("CE", "PE"):
            return self.segment_config("nse_commodity_options")
        return None

    def _classify_currency_derivatives(self, raw_row, instrument_type):
        """
        Route a currency-segment row, which mixes currency pairs, government bond derivatives, and the overnight rate index.

        Args:
            raw_row (dict): One raw row from zerodha.instruments.
            instrument_type (str): The row's instrument type.

        Returns:
            dict | None: The matched segment configuration, or None.
        """
        name = raw_row.get("name")
        if instrument_type == "FUT":
            if name in CURRENCY_NAMES:
                return self.segment_config("nse_currency_futures")
            if name == "ONMIBOR":
                return self.segment_config("nse_fixed_income_index_futures")
            return self.segment_config("nse_fixed_income_futures")
        if instrument_type in ("CE", "PE"):
            if name in CURRENCY_NAMES:
                return self.segment_config("nse_currency_options")
            return self.segment_config("nse_fixed_income_options")
        return None

    def to_identity(self, raw_row, segment_configuration):
        """
        Build the unified identity fields, resolving bond ISINs, stripping series suffixes, and aliasing index names.

        Args:
            raw_row (dict): One raw row from zerodha.instruments.
            segment_configuration (dict): The segment configuration whose identity mapping applies.

        Returns:
            dict: Identity fields, as described in BrokerMappingAdapter.to_identity.

        Raises:
            ValueError: If a bond row's exchange token has no match in the shared security identifier map, since the ISIN is that segment's identity.
        """
        segment = segment_configuration["segment"]

        if segment in ("nse_fixed_income", "bse_fixed_income"):
            exchange_token = str(raw_row.get("exchange_token"))
            isin = self.isin_by_token.get(exchange_token)
            if isin is None:
                raise ValueError(
                    f"no shared security identifier match for exchange token {exchange_token!r}, "
                    f"so this fixed income row cannot be identified by ISIN"
                )
            return {
                "symbol": isin,
            }

        identity = super().to_identity(raw_row, segment_configuration)

        if segment == "nse_equities":
            identity["symbol"] = SERIES_SUFFIX_PATTERN.sub("", identity["symbol"])
        elif segment == "nse_investment_trusts":
            identity["symbol"] = TRUST_SUFFIX_PATTERN.sub("", identity["symbol"])
        elif segment == "nse_mutual_funds":
            identity["symbol"] = MUTUAL_FUND_SUFFIX_PATTERN.sub("", identity["symbol"])
        elif segment == "nse_equity_indices":
            normalized = normalize_index_name(identity["symbol"])
            if normalized in NSE_INDEX_ALIASES:
                identity["symbol"] = NSE_INDEX_ALIASES[normalized]
            elif normalized in self.nse_index_master_lookup:
                identity["symbol"] = self.nse_index_master_lookup[normalized]
        elif segment == "bse_equity_indices":
            identity["symbol"] = BSE_INDEX_ALIASES.get(identity["symbol"], identity["symbol"])
        elif segment == "mcx_commodity_indices":
            identity["symbol"] = MCX_INDEX_ALIASES.get(identity["symbol"], identity["symbol"])
        elif segment == "nse_commodities":
            name = raw_row.get("name")
            if is_blank(name) or name == MISLABELLED_COMMODITY_NAME:
                identity["symbol"] = raw_row.get("tradingsymbol")
        return identity

    def to_broker_fields(self, raw_row, segment_configuration):
        """
        Build the per-broker mapping fields, falling back to the trading symbol where the name is blank.

        Args:
            raw_row (dict): One raw row from zerodha.instruments.
            segment_configuration (dict): The segment configuration whose broker field mapping applies.

        Returns:
            dict: Keys "broker_token" (str), "broker_symbol", "lot_size" (float | None), and "tick_size" (float | None).
        """
        broker_fields = super().to_broker_fields(raw_row, segment_configuration)
        segment = segment_configuration["segment"]
        if segment in BROKER_SYMBOL_FALLBACK_SEGMENTS and is_blank(broker_fields["broker_symbol"]):
            broker_fields["broker_symbol"] = raw_row.get("tradingsymbol")
        if segment == "nse_commodities":
            broker_fields["lot_size"] = None
            broker_fields["tick_size"] = None
        return broker_fields

    def uncategorised_exchange(self, raw_row):
        """
        Determine the canonical exchange for an unmatched Zerodha row from its exchange column.

        Args:
            raw_row (dict): One raw row from zerodha.instruments.

        Returns:
            str | None: "nse", "bse", or "mcx", or None for any other value.
        """
        exchange_identifier = raw_row.get("exchange")
        if exchange_identifier in ("NSE", "NFO", "CDS", "NCO"):
            return "nse"
        if exchange_identifier in ("BSE", "BFO"):
            return "bse"
        if exchange_identifier == "MCX":
            return "mcx"
        return None


if __name__ == "__main__":
    import argparse

    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--date", type=str, default=None)
    arguments = argument_parser.parse_args()
    ZerodhaMappingAdapter().run(date_class.fromisoformat(arguments.date) if arguments.date else date_class.today())
