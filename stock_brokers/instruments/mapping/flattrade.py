"""
Flattrade mapping adapter.

Flattrade's file needs work at every stage of the pipeline, most of it about rows rather than columns.

The fetch itself is part of the classification. Around 884 NSE symbols are listed twice, once under the EQ series and once under BE, and the EQ row should win; rows are therefore read with the EQ rows last, so the run's own last-write-wins collapse prefers them. A further hundred or so rows ship with both exchange and instrument blank, a gap in Flattrade's own file. Their tokens are matched against the BSE equity token space of the brokers whose files are complete, which recovers almost all of them as real BSE equities. Those recovered rows are read separately, tagged, and placed **first**, so a symbol present in both batches keeps its real row rather than the recovered one.

Classification then decides three things no rule can: whether an ambiguous NSE EQ or BE row, or BSE A or B row, is a plain equity, a real exchange traded fund, or a fund to leave alone, which is a priority decision between two segments matching the same predicate; and which NSE index rows are bond-shaped and do not belong in the equity index segment.

Two data faults are corrected on the way out. BSE option rows mis-round half-point strikes, reporting a real 102.5 as 103.0, so the true strike is re-extracted from the trading symbol. And the file carries no tick size column at all, so every segment's tick size resolves to nothing.
"""

import re
from datetime import date as date_class

import pandas as pd
from sqlalchemy import text

from stock_brokers.instruments.mapping.base import BrokerMappingAdapter
from stock_brokers.instruments.mapping.utilities.crossref import (
    equity_index_lookup,
    known_bse_etf_symbols,
    known_bse_fund_symbols,
    known_nse_etf_symbols,
    known_nse_fund_symbols,
)

RECOVERED_BSE_EQUITY_FLAG = "recovered_bse_equity"

STRIKE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)(?:CE|PE)$")

NSE_INDEX_ALIASES = {
    "NIFTY MID SELECT": "MIDCPNIFTY",
    "NIFTY MIDCAP 100": "NIFTY MID100 FREE",
    "Nifty Midcap 50": "NIFTYMCAP50",
    "NIFTY100 EQL Wgt": "NIFTY100 EQUAL WEIGHT",
    "NIFTY100 LowVol30": "NIFTY100 LOW VOLATILITY 30",
    "NIFTY SMLCAP 100": "NIFTY SMALLCAP 100",
    "NIFTY SMLCAP 250": "NIFTY SMALLCAP 250",
    "NIFTY SMLCAP 50": "NIFTY SMALLCAP 50",
    "NIFTY MIDSML 400": "NIFTY MIDSMALLCAP 400",
}

BSE_INDEX_ALIASES = {
    "SENSEX50": "SNSX50",
}

EXCLUDED_NSE_INDEX_PREFIXES = (
    "BHARATBOND-",
    "Nifty GS",
)

BSE_OPTION_SEGMENTS = (
    "bse_equity_options",
    "bse_equity_index_options",
)


def normalize_index_name(name):
    """
    Reduce an index name to uppercase alphanumerics so that differently-spelled broker names collide.

    Args:
        name (str): The raw index name.

    Returns:
        str: The name with every non-alphanumeric character removed and uppercased.
    """
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


def bse_equity_tokens(connection, mapping_date):
    """
    Collect the BSE equity token space from the brokers whose files carry a complete exchange column.

    Flattrade shares the exchange-assigned token numbering with Dhan and Stoxkart, so a blank-exchange Flattrade row whose token appears in their BSE equity lists is itself a BSE equity.

    Args:
        connection (sqlalchemy.engine.Connection): An open SQLAlchemy connection.
        mapping_date (datetime.date): The snapshot date to read.

    Returns:
        set: BSE equity tokens, as strings.
    """
    tokens = set()
    dhan_rows = connection.execute(
        text(
            "SELECT security_id FROM dhan.instruments WHERE download_date = :d "
            "AND exch_id = 'BSE' AND segment = 'E' AND instrument_type = 'ES'"
        ),
        {
            "d": mapping_date,
        },
    ).all()
    for row in dhan_rows:
        tokens.add(str(row.security_id))

    stoxkart_rows = connection.execute(
        text(
            "SELECT token FROM stoxkart.instruments WHERE download_date = :d "
            "AND exchange = 'BSE' AND instrument_type = 'EQUITIES'"
        ),
        {
            "d": mapping_date,
        },
    ).all()
    for row in stoxkart_rows:
        tokens.add(str(row.token))
    return tokens


class FlattradeMappingAdapter(BrokerMappingAdapter):
    """Mapping adapter for Flattrade, covering 21 real segments plus the uncategorised buckets."""

    BROKER_NAME = "flattrade"

    def run(self, mapping_date):
        """
        Map Flattrade's raw rows for one date, precomputing the four allowlists and the index lookup first.

        Args:
            mapping_date (datetime.date): The raw snapshot date to map.

        Returns:
            dict: The run summary, as described in BrokerMappingAdapter.run.
        """
        with self.engine.connect() as connection:
            self.nse_fund_symbols = known_nse_fund_symbols(connection, mapping_date)
            self.nse_etf_symbols = known_nse_etf_symbols(connection, mapping_date)
            self.bse_fund_symbols = known_bse_fund_symbols(connection, mapping_date)
            self.bse_etf_symbols = known_bse_etf_symbols(connection, mapping_date)
            self.nse_index_master_lookup = equity_index_lookup(connection, mapping_date)


        return super().run(mapping_date)

    def read_raw_rows(self, connection, mapping_date):
        """
        Read Flattrade's rows in the order the classification depends on, marking the blank-exchange rows that can be recovered.

        Two orderings are imposed at once. The EQ rows come last, so they win the collapse over a same-symbol BE row. The blank-exchange rows come first, so a real row for the same symbol wins over a recovered one.

        The recovery marks rows in place rather than reading them a second time. Reading them twice puts each blank-exchange row through the classification twice, once recovered and once not, and the second pass files a duplicate into the uncategorised bucket.

        Args:
            connection (sqlalchemy.engine.Connection): An open SQLAlchemy connection.
            mapping_date (datetime.date): The raw snapshot date to read.

        Returns:
            pandas.DataFrame: The raw rows, ordered, with a flag column marking the recovered ones.
        """
        raw = pd.read_sql(
            text(
                "SELECT * FROM flattrade.instruments WHERE download_date = :d "
                "ORDER BY (exchange IS NULL OR exchange = '') DESC, (instrument = 'EQ') ASC"
            ),
            connection,
            params={
                "d": mapping_date,
            },
        )
        if raw.empty:
            return raw

        tokens = bse_equity_tokens(connection, mapping_date)
        recovered_flags = []
        for exchange, token in zip(raw["exchange"], raw["token"]):
            is_blank = exchange is None or pd.isna(exchange) or str(exchange).strip() == ""
            recovered_flags.append(is_blank and str(token) in tokens)
        return raw.assign(**{RECOVERED_BSE_EQUITY_FLAG: recovered_flags})

    def classify(self, raw_row):
        """
        Classify a raw row, deciding the ambiguous equity, fund, and index cases before the rules engine.

        Args:
            raw_row (dict): One raw row from flattrade.instruments.

        Returns:
            dict | None: The matched segment configuration, or None when no segment matches.
        """
        exchange = raw_row.get("exchange")
        instrument = raw_row.get("instrument")

        if raw_row.get(RECOVERED_BSE_EQUITY_FLAG) is True:
            if raw_row.get("tradingsymbol") in self.bse_fund_symbols:
                return None
            return self.segment_config("bse_equities")

        if exchange == "NSE" and instrument in ("EQ", "BE"):
            symbol = raw_row.get("symbol")
            if symbol in self.nse_etf_symbols:
                return self.segment_config("nse_exchange_traded_funds")
            if symbol in self.nse_fund_symbols:
                return None
            return self.segment_config("nse_equities")

        if exchange == "BSE" and instrument in ("A", "B"):
            trading_symbol = raw_row.get("tradingsymbol")
            if trading_symbol in self.bse_etf_symbols:
                return self.segment_config("bse_exchange_traded_funds")
            if trading_symbol in self.bse_fund_symbols:
                return None
            return self.segment_config("bse_equities")

        if exchange == "NSE" and instrument == "INDEX":
            trading_symbol = str(raw_row.get("tradingsymbol") or "")
            for excluded_prefix in EXCLUDED_NSE_INDEX_PREFIXES:
                if trading_symbol.startswith(excluded_prefix):
                    return None

        return super().classify(raw_row)

    def to_identity(self, raw_row, segment_configuration):
        """
        Build the unified identity fields, correcting the BSE strike rounding and resolving index names.

        Args:
            raw_row (dict): One raw row from flattrade.instruments.
            segment_configuration (dict): The segment configuration whose identity mapping applies.

        Returns:
            dict: Identity fields, as described in BrokerMappingAdapter.to_identity.

        Raises:
            ValueError: If an expiry value is numeric with no explicit transform.
        """
        identity = super().to_identity(raw_row, segment_configuration)
        segment = segment_configuration["segment"]

        if segment in BSE_OPTION_SEGMENTS:
            match = STRIKE_PATTERN.search(str(raw_row.get("tradingsymbol") or ""))
            if match:
                identity["strike_price"] = float(match.group(1))
        elif segment == "bse_equity_indices":
            identity["symbol"] = BSE_INDEX_ALIASES.get(identity["symbol"], identity["symbol"])
        elif segment == "nse_equity_indices":
            name = raw_row.get("symbol")
            if name in NSE_INDEX_ALIASES:
                identity["symbol"] = NSE_INDEX_ALIASES[name]
            else:
                normalized = normalize_index_name(name)
                if normalized in self.nse_index_master_lookup:
                    identity["symbol"] = self.nse_index_master_lookup[normalized]
        return identity

    def uncategorised_exchange(self, raw_row):
        """
        Determine the canonical exchange for an unmatched Flattrade row from its exchange column.

        Args:
            raw_row (dict): One raw row from flattrade.instruments.

        Returns:
            str | None: "nse", "bse", or "mcx", or None when the exchange is blank or unknown.
        """
        exchange_identifier = raw_row.get("exchange")
        if exchange_identifier in ("NSE", "NFO", "CDS"):
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
    FlattradeMappingAdapter().run(date_class.fromisoformat(arguments.date) if arguments.date else date_class.today())
