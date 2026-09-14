"""
Stoxkart mapping adapter.

Stoxkart needs more override logic than any other broker in this build. Its raw file carries several rows for the same instrument, marks calendar spreads and reference rows inside the same instrument type as real contracts, and scales strikes and ticks differently across its own segments.

The overrides fall into four groups:

- Cross-row winner sets, computed once per run because no row-local rule can express them: NSE equities and BSE equities pick one row per symbol by series priority, BSE fixed income picks one row per ISIN (the file carries a normal market-lot row plus odd-lot duplicates), and MCX options pick one row per contract by highest token.
- Cross-broker and cross-segment lookups: the BSE exchange traded fund allowlist, and the NSE index name resolution against the day's already-written master rows.
- Exclusions and redirects no equality rule can express: the "SP-" calendar spread prefix on NSE derivatives, regular expression single-leg matching on the BSE currency and fixed income derivative segments, the index-name exclusion lists on MCX and NCDEX spot rows, and the ISIN checks that separate funds from equities and bonds.
- Value scaling that is not uniform across the broker's own segments: strikes and ticks divide by 100 on the equity family and the commodity options, and by ten million on every currency and fixed income derivative segment.

Expiry dates arrive as ``DD-MM-YYYY`` text on every date-bearing segment, so each one names the ``day_month_year_date`` transform explicitly rather than relying on the generic parser, which would read any day of 12 or less as a month.
"""

import re
from datetime import date as date_class

import pandas as pd
from sqlalchemy import text

from stock_brokers.instruments.mapping.base import BrokerMappingAdapter
from stock_brokers.instruments.mapping.utilities.crossref import equity_index_lookup, known_bse_etf_symbols

NSE_EQUITIES_SERIES_PRIORITY = (
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
    "P1",
    "X1",
)

BSE_EQUITIES_CLEAN_SERIES = (
    "M",
    "MS",
    "MT",
    "NS",
    "NT",
    "P",
    "R",
    "T",
    "TS",
    "W",
    "X",
    "XT",
    "Y",
    "ZP",
)

BSE_EQUITIES_LEAK_SERIES = (
    "A",
    "B",
)

BSE_EQUITIES_LOSING_SERIES = (
    "NS",
    "NT",
)

BSE_FIXED_INCOME_SERIES = (
    "F",
    "FC",
    "G",
    "GC",
)

BSE_FIXED_INCOME_WINNING_SERIES = (
    "F",
    "G",
)

NSE_FIXED_INCOME_NON_BOND_SERIES = (
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
    "P1",
    "X1",
    "EI",
    "MF",
    "SF",
    "IV",
    "RR",
)

NSE_RATE_UNDERLYING_TYPES = (
    "UNDIRC",
    "UNDIRT",
)

BSE_FIXED_INCOME_FUTURE_TYPES = (
    "FUTIRD",
    "FUTIRT",
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

NCDEX_INDEX_NAMES = (
    "AGRIDEX",
    "GUAREX",
    "SOYDEX",
)

BSE_CURRENCY_FUTURE_NAMES = (
    "EURINR",
    "EURUSD",
    "GBPINR",
    "GBPUSD",
    "JPYINR",
    "USDINR",
    "USDJPY",
)

BSE_CURRENCY_OPTION_NAMES = BSE_CURRENCY_FUTURE_NAMES + (
    "USDINR-CNV",
    "USDINR-STD",
)

NSE_INDEX_EXCLUDED_SYMBOLS = (
    "BeESNAV",
    "SHARIAH",
)

NSE_INDEX_ALIASES = {
    "NIFTYBANK": "BANKNIFTY",
    "NIFTYFINSERVICE": "FINNIFTY",
    "NIFTYMIDSELECT": "MIDCPNIFTY",
    "NIFTY50": "NIFTY",
    "NIFTY100EQLWGT": "NIFTY100 EQUAL WEIGHT",
    "NIFTY100LOWVOL30": "NIFTY100 LOW VOLATILITY 30",
    "NIFTYMIDSML400": "NIFTY MIDSMALLCAP 400",
    "NIFTYMIDCAP100": "NIFTY MID100 FREE",
    "NIFTYMIDCAP50": "NIFTYMCAP50",
    "NIFTYNEXT50": "NIFTYNXT50",
    "NIFTYSMLCAP250": "NIFTY SMALLCAP 250",
    "NIFTYSMLCAP50": "NIFTY SMALLCAP 50",
    "NIFTYSMLCAP100": "NIFTY SMALLCAP 100",
    "NIFTYQUALITY30": "NIFTY100 QUALTY30",
}

BSE_INDEX_ALIASES = {
    "BSETECK": "TECK",
}

NULL_LOT_AND_TICK_SEGMENTS = (
    "nse_currencies",
    "bse_currencies",
    "nse_fixed_income_indices",
    "bse_fixed_income_indices",
)

NULL_TICK_SEGMENTS = (
    "nse_equity_indices",
    "bse_equity_indices",
)

MONTH_NAMES = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"
FUTURE_PATTERN = re.compile(rf"^[A-Z0-9]+\d{{2}}(?:(?:{MONTH_NAMES})|[1-9OND]\d{{2}})FUT$")
OPTION_PATTERN = re.compile(rf"^[A-Z0-9]+\d{{2}}(?:(?:{MONTH_NAMES})|[1-9OND]\d{{2}})\d+(?:\.\d+)?(?:CE|PE)$")
CURRENCY_OPTION_ALTERNATE_PATTERN = re.compile(rf"^USD (?:CNV|STD) \d{{2}}-(?:{MONTH_NAMES}) \d+(?:\.\d+)?$")
NCDEX_SPREAD_PATTERN = re.compile(rf"^(.*?)({MONTH_NAMES})({MONTH_NAMES})?(\d{{4}})$")


def normalize_index_name(name):
    """
    Reduce an index name to uppercase alphanumerics so that differently-spelled broker names collide.

    Args:
        name (str): The raw index name from a broker table.

    Returns:
        str: The name with every non-alphanumeric character removed and uppercased.
    """
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


def isin_missing(value):
    """
    Check whether an ISIN value is absent, which pandas may represent as either None or NaN.

    Args:
        value (str | float | None): The raw ISIN value from a Stoxkart row.

    Returns:
        bool: True when there is no usable ISIN.
    """
    return value is None or pd.isna(value) or str(value).strip() == ""


def token_sort_key(token):
    """
    Build a sort key for a broker token that orders numerically where the token is a number.

    Stoxkart's tokens are stored as text, so a plain string sort would order "800178" before "9" and break the lowest-token tie-break the fixed income winner set depends on.

    Args:
        token (str): The raw token value.

    Returns:
        tuple: A (is_not_numeric, numeric_value, text_value) triple usable as a sort key.
    """
    text_value = str(token)
    if text_value.isdigit():
        return (0, int(text_value), text_value)
    return (1, 0, text_value)


class StoxkartMappingAdapter(BrokerMappingAdapter):
    """Mapping adapter for Stoxkart, covering 39 real segments plus the uncategorised buckets."""

    BROKER_NAME = "stoxkart"

    def run(self, mapping_date):
        """
        Map Stoxkart's raw rows for one date, precomputing the four winner sets and the two lookups first.

        Args:
            mapping_date (datetime.date): The raw snapshot date to map.

        Returns:
            dict: The run summary, as described in BrokerMappingAdapter.run.
        """
        with self.engine.connect() as connection:
            raw = pd.read_sql(
                text(
                    "SELECT token, symbol, series, exchange, instrument_type, isin_code, "
                    "expiry_date, strike_price, option_type "
                    "FROM stoxkart.instruments WHERE download_date = :d"
                ),
                connection,
                params={
                    "d": mapping_date,
                },
            )
            self.bse_etf_symbols = known_bse_etf_symbols(connection, mapping_date)
            self.nse_index_master_lookup = equity_index_lookup(connection, mapping_date)


        raw_rows = raw.to_dict("records")
        self.nse_equities_winning_tokens = self._nse_equities_winners(raw_rows)
        self.bse_equities_winning_tokens = self._bse_equities_winners(raw_rows)
        self.bse_fixed_income_winning_tokens = self._bse_fixed_income_winners(raw_rows)
        self.mcx_options_winning_tokens = self._mcx_options_winners(raw_rows)

        return super().run(mapping_date)

    def _nse_equities_winners(self, raw_rows):
        """
        Pick one NSE equity row per symbol, by series priority.

        Args:
            raw_rows (list[dict]): Every raw Stoxkart row for the date.

        Returns:
            set: The winning tokens, as strings.
        """
        best_by_symbol = {}
        for raw_row in raw_rows:
            if raw_row.get("exchange") != "NSE":
                continue
            series = raw_row.get("series")
            if series not in NSE_EQUITIES_SERIES_PRIORITY:
                continue
            isin = raw_row.get("isin_code")
            if isin_missing(isin) or str(isin).startswith("INF"):
                continue
            symbol = raw_row.get("symbol")
            priority = NSE_EQUITIES_SERIES_PRIORITY.index(series)
            current = best_by_symbol.get(symbol)
            if current is None or priority < current[0]:
                best_by_symbol[symbol] = (priority, str(raw_row.get("token")))

        winners = set()
        for priority, token in best_by_symbol.values():
            winners.add(token)
        return winners

    def _bse_equities_winners(self, raw_rows):
        """
        Pick one BSE equity row per symbol, preferring a series other than NS or NT.

        Args:
            raw_rows (list[dict]): Every raw Stoxkart row for the date.

        Returns:
            set: The winning tokens, as strings.
        """
        best_by_symbol = {}
        for raw_row in raw_rows:
            if raw_row.get("exchange") != "BSE":
                continue
            symbol = raw_row.get("symbol")
            if not symbol or str(symbol).endswith("#"):
                continue
            series = raw_row.get("series")
            isin = raw_row.get("isin_code")
            is_clean = series in BSE_EQUITIES_CLEAN_SERIES
            is_leaked_non_fund = series in BSE_EQUITIES_LEAK_SERIES and not (
                not isin_missing(isin) and str(isin).startswith("INF")
            )
            if not is_clean and not is_leaked_non_fund:
                continue
            priority = 1 if series in BSE_EQUITIES_LOSING_SERIES else 0
            current = best_by_symbol.get(symbol)
            if current is None or priority < current[0]:
                best_by_symbol[symbol] = (priority, str(raw_row.get("token")))

        winners = set()
        for priority, token in best_by_symbol.values():
            winners.add(token)
        return winners

    def _bse_fixed_income_winners(self, raw_rows):
        """
        Pick one BSE fixed income row per ISIN, preferring the normal market lot and then the lowest token.

        Stoxkart's file carries two or three rows for the same bond: one normal F or G series row, plus FC and GC odd-lot duplicates with lot sizes in the hundreds of thousands. Without this choice the stored token flips between dates depending on which row the database happens to write last.

        Args:
            raw_rows (list[dict]): Every raw Stoxkart row for the date.

        Returns:
            set: The winning tokens, as strings.
        """
        best_by_isin = {}
        for raw_row in raw_rows:
            if raw_row.get("exchange") != "BSE":
                continue
            if raw_row.get("series") not in BSE_FIXED_INCOME_SERIES:
                continue
            isin = raw_row.get("isin_code")
            if isin_missing(isin) or str(isin).startswith("INF"):
                continue
            priority = 0 if raw_row.get("series") in BSE_FIXED_INCOME_WINNING_SERIES else 1
            token = str(raw_row.get("token"))
            candidate = (priority, token_sort_key(token), token)
            current = best_by_isin.get(isin)
            if current is None or candidate < current:
                best_by_isin[isin] = candidate

        winners = set()
        for priority, sort_key, token in best_by_isin.values():
            winners.add(token)
        return winners

    def _mcx_options_winners(self, raw_rows):
        """
        Pick one MCX option row per contract, keeping the highest token where the file lists a contract twice.

        Args:
            raw_rows (list[dict]): Every raw Stoxkart row for the date.

        Returns:
            set: The winning tokens, as strings.
        """
        best_by_contract = {}
        for raw_row in raw_rows:
            if raw_row.get("exchange") != "MCX" or raw_row.get("instrument_type") != "OPTFUT":
                continue
            contract = (
                raw_row.get("symbol"),
                raw_row.get("expiry_date"),
                raw_row.get("strike_price"),
                raw_row.get("option_type"),
            )
            token = str(raw_row.get("token"))
            candidate = (token_sort_key(token), token)
            current = best_by_contract.get(contract)
            if current is None or candidate > current:
                best_by_contract[contract] = candidate

        winners = set()
        for sort_key, token in best_by_contract.values():
            winners.add(token)
        return winners

    def classify(self, raw_row):
        """
        Classify a raw row, running the code-driven checks around the rules engine.

        The early checks run first, so a segment whose real condition is a winner set, a crossref allowlist, or a regular expression always wins over a broader rule listed for a different segment. The rules engine runs next, and its match is then post-filtered. Anything still unmatched goes through the fallback checks for the segments that have no rules at all.

        Args:
            raw_row (dict): One raw row from stoxkart.instruments.

        Returns:
            dict | None: The matched segment configuration, or None when no segment matches.
        """
        early = self._classify_early(raw_row)
        if early is not None:
            return early
        segment_configuration = super().classify(raw_row)
        if segment_configuration is not None:
            return self._post_filter(raw_row, segment_configuration)
        return self._classify_fallback(raw_row)

    def _classify_early(self, raw_row):
        """
        Check the segments whose real condition cannot be a rule and must win over any rule.

        Args:
            raw_row (dict): One raw row from stoxkart.instruments.

        Returns:
            dict | None: The matched segment configuration, or None to leave the row to the rules engine.
        """
        exchange = raw_row.get("exchange")
        symbol = raw_row.get("symbol")
        instrument_type = raw_row.get("instrument_type")
        description = str(raw_row.get("symbol_description") or "")

        if exchange == "BSE":
            series = raw_row.get("series")
            isin = raw_row.get("isin_code")
            if symbol in self.bse_etf_symbols:
                return self.segment_config("bse_exchange_traded_funds")
            if symbol and not str(symbol).endswith("#"):
                is_clean = series in BSE_EQUITIES_CLEAN_SERIES
                is_leaked_non_fund = series in BSE_EQUITIES_LEAK_SERIES and not (
                    not isin_missing(isin) and str(isin).startswith("INF")
                )
                if is_clean or is_leaked_non_fund:
                    if str(raw_row.get("token")) in self.bse_equities_winning_tokens:
                        return self.segment_config("bse_equities")
                    return None
            if series in BSE_FIXED_INCOME_SERIES:
                if isin_missing(isin) or str(isin).startswith("INF"):
                    return None
                if str(raw_row.get("token")) not in self.bse_fixed_income_winning_tokens:
                    return None
                return self.segment_config("bse_fixed_income")

        if exchange == "BSECD":
            is_overnight_rate = str(symbol or "").startswith("ONMIBOR")
            if instrument_type in BSE_FIXED_INCOME_FUTURE_TYPES and not is_overnight_rate:
                if FUTURE_PATTERN.match(description):
                    return self.segment_config("bse_fixed_income_futures")
                return None
            if instrument_type == "FUTIRD" and is_overnight_rate:
                if FUTURE_PATTERN.match(description):
                    return self.segment_config("bse_fixed_income_index_futures")
                return None
            if instrument_type == "OPTIRD":
                return self.segment_config("bse_fixed_income_options")
            if instrument_type == "FUTCUR" and symbol in BSE_CURRENCY_FUTURE_NAMES:
                if FUTURE_PATTERN.match(description):
                    return self.segment_config("bse_currency_futures")
                return None
            if instrument_type == "OPTCUR" and symbol in BSE_CURRENCY_OPTION_NAMES:
                if OPTION_PATTERN.match(description) or CURRENCY_OPTION_ALTERNATE_PATTERN.match(description):
                    return self.segment_config("bse_currency_options")
                return None

        if exchange == "MCX" and instrument_type == "SPOT":
            if symbol in MCX_INDEX_NAMES:
                return None
            return self.segment_config("mcx_commodities")

        if exchange == "NCDEX":
            if instrument_type == "SPOT":
                if symbol in NCDEX_INDEX_NAMES:
                    return None
                return self.segment_config("ncdex_commodities")
            if instrument_type == "FUTCOM":
                spread_match = NCDEX_SPREAD_PATTERN.match(description)
                if spread_match and spread_match.group(3):
                    return None
                return self.segment_config("ncdex_commodity_futures")

        return None

    def _post_filter(self, raw_row, segment_configuration):
        """
        Apply the exclusions and redirects that follow a rules-engine match.

        Args:
            raw_row (dict): One raw row from stoxkart.instruments.
            segment_configuration (dict): The segment the rules engine matched.

        Returns:
            dict | None: The final segment configuration, or None to leave the row uncategorised.
        """
        segment = segment_configuration["segment"]
        description = str(raw_row.get("symbol_description") or "")

        if segment == "nse_equities":
            isin = raw_row.get("isin_code")
            if not isin_missing(isin) and str(isin).startswith("INF"):
                return self.segment_config("nse_exchange_traded_funds")
            if isin_missing(isin):
                symbol = raw_row.get("symbol")
                if self._is_nse_index_row(raw_row) and raw_row.get("series") == "EQ":
                    return self.segment_config("nse_equity_indices")
                return None
            if str(raw_row.get("token")) not in self.nse_equities_winning_tokens:
                return None
            return segment_configuration

        if segment in ("nse_equity_futures", "nse_equity_index_futures", "nse_currency_futures", "nse_fixed_income_futures"):
            if description.startswith("SP-"):
                return None
            if segment == "nse_fixed_income_futures" and str(raw_row.get("symbol") or "").startswith("ONMIBOR"):
                return self.segment_config("nse_fixed_income_index_futures")
            return segment_configuration

        if segment == "mcx_commodity_options":
            if str(raw_row.get("token")) not in self.mcx_options_winning_tokens:
                return None
            return segment_configuration

        if segment == "mcx_commodity_indices" and raw_row.get("symbol") not in MCX_INDEX_NAMES:
            return None

        return segment_configuration

    def _is_nse_index_row(self, raw_row):
        """
        Check the exclusions that separate a real NSE index row from a fund net asset value or bond index row.

        Args:
            raw_row (dict): One raw row from stoxkart.instruments.

        Returns:
            bool: True when the row is a real NSE equity index.
        """
        symbol = raw_row.get("symbol")
        description = raw_row.get("symbol_description")
        if symbol in NSE_INDEX_EXCLUDED_SYMBOLS:
            return False
        if isinstance(symbol, str) and symbol.startswith("BHABOAPR"):
            return False
        if isinstance(description, str) and description.startswith("Nifty GS"):
            return False
        return True

    def _classify_fallback(self, raw_row):
        """
        Classify the segments that have no rules at all, for logic no equality rule can express.

        Args:
            raw_row (dict): One raw row from stoxkart.instruments.

        Returns:
            dict | None: The matched segment configuration, or None when the row stays uncategorised.
        """
        exchange = raw_row.get("exchange")
        symbol = raw_row.get("symbol")
        instrument_type = raw_row.get("instrument_type")

        if exchange == "NSE":
            series = raw_row.get("series")
            isin = raw_row.get("isin_code")
            is_index_series = series == "EI" or (series == "EQ" and isin_missing(isin))
            if is_index_series and self._is_nse_index_row(raw_row):
                return self.segment_config("nse_equity_indices")
            if (
                series
                and not pd.isna(series)
                and series not in NSE_FIXED_INCOME_NON_BOND_SERIES
                and not isin_missing(isin)
                and not str(isin).startswith("INF")
            ):
                return self.segment_config("nse_fixed_income")

        if exchange == "NSECD":
            if instrument_type in NSE_RATE_UNDERLYING_TYPES and symbol != "ONMIBOR":
                return self.segment_config("nse_fixed_income")
            if instrument_type == "FUTIRC" and symbol == "ONMIBOR":
                description = str(raw_row.get("symbol_description") or "")
                if FUTURE_PATTERN.match(description):
                    return self.segment_config("nse_fixed_income_index_futures")

        if exchange == "NCDEX":
            description = raw_row.get("symbol_description")
            if instrument_type == "SPOT" and symbol in NCDEX_INDEX_NAMES:
                return self.segment_config("ncdex_commodity_indices")
            if instrument_type == "EQTY" and description != "AGRIDEX":
                return self.segment_config("ncdex_commodity_indices")

        return None

    def to_identity(self, raw_row, segment_configuration):
        """
        Build the unified identity fields, applying Stoxkart's per-segment identity sources.

        Args:
            raw_row (dict): One raw row from stoxkart.instruments.
            segment_configuration (dict): The segment configuration whose identity mapping applies.

        Returns:
            dict: Identity fields, as described in BrokerMappingAdapter.to_identity.

        Raises:
            ValueError: If an NCDEX option row has an unparseable or missing expiry, strike, or option type, which the run counts as a per-row error rather than writing a mis-identified instrument.
        """
        segment = segment_configuration["segment"]

        if segment == "nse_equity_indices":
            name = raw_row.get("symbol_description")
            normalized = normalize_index_name(name)
            if normalized in NSE_INDEX_ALIASES:
                return {
                    "symbol": NSE_INDEX_ALIASES[normalized],
                }
            if normalized in self.nse_index_master_lookup:
                return {
                    "symbol": self.nse_index_master_lookup[normalized],
                }
            return {
                "symbol": name,
            }

        if segment == "bse_equity_indices":
            symbol = raw_row.get("symbol")
            return {
                "symbol": BSE_INDEX_ALIASES.get(symbol, symbol),
            }

        if segment == "nse_fixed_income":
            if raw_row.get("exchange") == "NSECD":
                return {
                    "symbol": str(raw_row.get("symbol")).strip(),
                }
            return {
                "symbol": str(raw_row.get("isin_code")).strip(),
            }

        if segment == "ncdex_commodity_options":
            identity = super().to_identity(raw_row, segment_configuration)
            if (
                identity.get("expiry_date") is None
                or identity.get("strike_price") is None
                or not identity.get("option_type")
            ):
                raise ValueError(
                    "ncdex_commodity_options: the row has an unparseable or missing expiry, "
                    "strike price, or option type"
                )
            return identity

        return super().to_identity(raw_row, segment_configuration)

    def to_broker_fields(self, raw_row, segment_configuration):
        """
        Build the per-broker mapping fields, applying Stoxkart's per-segment lot and tick handling.

        The NSE cash half of ``nse_fixed_income`` carries real sizes with the tick in hundredths, while the NSECD rate-underlying half and the currency and rate index segments carry no meaningful sizes at all. The NSE and BSE equity indices carry a tick of 1 on every row whatever the index's real tick, so their tick is dropped.

        Args:
            raw_row (dict): One raw row from stoxkart.instruments.
            segment_configuration (dict): The segment configuration whose broker field mapping applies.

        Returns:
            dict: Keys "broker_token" (str), "broker_symbol", "lot_size" (float | None), and "tick_size" (float | None).
        """
        segment = segment_configuration["segment"]
        broker_fields = super().to_broker_fields(raw_row, segment_configuration)

        if segment == "nse_fixed_income":
            if raw_row.get("exchange") == "NSECD":
                broker_fields["lot_size"] = None
                broker_fields["tick_size"] = None
            elif broker_fields["tick_size"] is not None:
                broker_fields["tick_size"] = broker_fields["tick_size"] / 100
            return broker_fields

        if segment in NULL_LOT_AND_TICK_SEGMENTS:
            broker_fields["lot_size"] = None
            broker_fields["tick_size"] = None
        if segment in NULL_TICK_SEGMENTS:
            broker_fields["tick_size"] = None
        return broker_fields

    def uncategorised_exchange(self, raw_row):
        """
        Determine the canonical exchange for an unmatched Stoxkart row from its exchange column.

        Args:
            raw_row (dict): One raw row from stoxkart.instruments.

        Returns:
            str | None: "nse", "bse", "mcx", or "ncdex", or None for any other value.
        """
        exchange_identifier = raw_row.get("exchange")
        if exchange_identifier in ("NSE", "NFO", "NSECD"):
            return "nse"
        if exchange_identifier in ("BSE", "BFO", "BSECD"):
            return "bse"
        if exchange_identifier == "MCX":
            return "mcx"
        if exchange_identifier == "NCDEX":
            return "ncdex"
        return None


if __name__ == "__main__":
    import argparse

    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--date", type=str, default=None)
    arguments = argument_parser.parse_args()
    StoxkartMappingAdapter().run(date_class.fromisoformat(arguments.date) if arguments.date else date_class.today())
