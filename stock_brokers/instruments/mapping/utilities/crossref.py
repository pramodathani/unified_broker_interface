"""
Cross-broker classification aids for the mapping adapters.

Four brokers — Zerodha, Shoonya, Flattrade, and IND Money — carry no ISIN column and have no way to self-verify whether a row is a fund, an exchange traded fund, an investment trust, or a bond rather than an equity. These helpers pool the signals of the brokers that do carry ISIN or an explicit fund tag, so the ISIN-less brokers can classify against another broker's already-resolved answer as a live cross-reference.

This is a deliberate, narrow exception to keeping each broker's adapter fully independent. A misfiled row is worse than an unmapped one: it gets a ticker-keyed identity in the wrong segment, and the same instrument filed correctly by an ISIN-bearing broker lands under a different identity, so the two never converge — the exact failure the id design exists to prevent.

These queries read each broker's raw snapshots from `<broker>.instruments`, since instrument snapshots live in their broker's own schema rather than in a shared one. The live verification quoted throughout the docstrings, the row counts and the named false positives, was established against real snapshots, and the queries rest on it. Re-check a specific claim before relying on it rather than assuming it has stayed true.
"""

import re

from sqlalchemy import text

from stock_brokers.instruments.mapping.utilities import tables


def known_bse_fund_symbols(connection, mapping_date):
    """
    Gather the trading symbols confirmed to be mutual funds or exchange traded funds on BSE.

    The signal is pooled from every broker that carries ISIN or an explicit fund tag, because a series or group code alone cannot tell a fund apart from an equity sharing the same code.

    Args:
        connection (sqlalchemy.engine.Connection): An open database connection.
        mapping_date (datetime.date): The raw snapshot date to draw from.

    Returns:
        set[str]: BSE trading symbols confirmed to be funds.
    """
    symbols = set()
    isin_queries = [
        (
            "SELECT ptrdsymbol AS symbol FROM kotak.instruments "
            "WHERE download_date = :d AND pexchseg = 'bse_cm' AND pisin LIKE 'INF%'"
        ),
        (
            "SELECT trading_symbol AS symbol FROM groww.instruments "
            "WHERE download_date = :d AND exchange = 'BSE' AND isin LIKE 'INF%'"
        ),
        (
            "SELECT symbol FROM stoxkart.instruments "
            "WHERE download_date = :d AND exchange = 'BSE' AND isin_code LIKE 'INF%'"
        ),
        (
            "SELECT underlying_symbol AS symbol FROM fyers.instruments "
            "WHERE download_date = :d AND exchange = '12' AND isin LIKE 'INF%'"
        ),
        (
            "SELECT name AS symbol FROM wisdom_capital.instruments "
            "WHERE download_date = :d AND exchangesegment = 'BSECM' AND isin LIKE 'INF%'"
        ),
    ]
    for query in isin_queries:
        rows = connection.execute(text(query), {"d": mapping_date}).all()
        for row in rows:
            if row.symbol:
                symbols.add(row.symbol)

    dhan_fund_rows = connection.execute(
        text(
            "SELECT underlying_symbol AS symbol FROM dhan.instruments "
            "WHERE download_date = :d AND exch_id = 'BSE' AND segment = 'E' "
            "AND instrument = 'EQUITY' AND instrument_type IN ('MF', 'ETF')"
        ),
        {"d": mapping_date},
    ).all()
    for row in dhan_fund_rows:
        if row.symbol:
            symbols.add(row.symbol)

    return symbols


def known_bse_investment_trust_symbols(connection, mapping_date):
    """
    Gather the trading symbols confirmed to be REITs or InvITs on BSE, from Kotak's explicit 'IF' group.

    Args:
        connection (sqlalchemy.engine.Connection): An open database connection.
        mapping_date (datetime.date): The raw snapshot date to draw from.

    Returns:
        set[str]: BSE trading symbols confirmed to be investment trusts.
    """
    rows = connection.execute(
        text(
            "SELECT ptrdsymbol AS symbol FROM kotak.instruments "
            "WHERE download_date = :d AND pexchseg = 'bse_cm' AND pgroup = 'IF'"
        ),
        {"d": mapping_date},
    ).all()
    symbols = set()
    for row in rows:
        if row.symbol:
            symbols.add(row.symbol)
    return symbols


def known_bse_fixed_income_symbols(connection, mapping_date):
    """
    Gather the trading symbols confirmed to be bonds or government securities on BSE, from Kotak's ISIN-verified 'F' and 'G' groups.

    Government security naming — treasury bills, state development loans with state-code suffixes, GOI and GS prefixed bonds — has too many naming variants for a reliable regular expression, which was found live while classifying Zerodha's BSE equities. Cross-referencing a broker that already resolved this via ISIN is more reliable than guessing a pattern.

    Args:
        connection (sqlalchemy.engine.Connection): An open database connection.
        mapping_date (datetime.date): The raw snapshot date to draw from.

    Returns:
        set[str]: BSE trading symbols confirmed to be fixed income.
    """
    rows = connection.execute(
        text(
            "SELECT ptrdsymbol AS symbol FROM kotak.instruments "
            "WHERE download_date = :d AND pexchseg = 'bse_cm' AND pgroup IN ('F', 'G')"
        ),
        {"d": mapping_date},
    ).all()
    symbols = set()
    for row in rows:
        if row.symbol:
            symbols.add(row.symbol)
    return symbols


def known_nse_fund_symbols(connection, mapping_date):
    """
    Gather the trading symbols confirmed to be mutual funds or exchange traded funds on NSE.

    Pooled the same way as known_bse_fund_symbols. Kotak's own 'EQ' group was found live to leak at least one INF-prefixed exchange traded fund ticker ("SILVERADD-EQ") on NSE, so a group code alone is not a reliable equity or fund discriminator here either.

    Args:
        connection (sqlalchemy.engine.Connection): An open database connection.
        mapping_date (datetime.date): The raw snapshot date to draw from.

    Returns:
        set[str]: NSE trading symbols confirmed to be funds.
    """
    symbols = set()
    isin_queries = [
        (
            "SELECT regexp_replace(ptrdsymbol, '-[A-Z0-9]+$', '') AS symbol "
            "FROM kotak.instruments "
            "WHERE download_date = :d AND pexchseg = 'nse_cm' AND pisin LIKE 'INF%'"
        ),
        (
            "SELECT trading_symbol AS symbol FROM groww.instruments "
            "WHERE download_date = :d AND exchange = 'NSE' AND isin LIKE 'INF%'"
        ),
        (
            "SELECT underlying_symbol AS symbol FROM fyers.instruments "
            "WHERE download_date = :d AND exchange = '10' AND isin LIKE 'INF%'"
        ),
        (
            "SELECT name AS symbol FROM wisdom_capital.instruments "
            "WHERE download_date = :d AND exchangesegment = 'NSECM' AND isin LIKE 'INF%'"
        ),
    ]
    for query in isin_queries:
        rows = connection.execute(text(query), {"d": mapping_date}).all()
        for row in rows:
            if row.symbol:
                symbols.add(row.symbol)

    dhan_fund_rows = connection.execute(
        text(
            "SELECT underlying_symbol AS symbol FROM dhan.instruments "
            "WHERE download_date = :d AND exch_id = 'NSE' AND segment = 'E' "
            "AND instrument = 'EQUITY' AND (instrument_type IN ('MF', 'ETF') "
            "OR (instrument_type = 'Other' AND series = 'SF'))"
        ),
        {"d": mapping_date},
    ).all()
    for row in dhan_fund_rows:
        if row.symbol:
            symbols.add(row.symbol)

    return symbols


def known_nse_investment_trust_symbols(connection, mapping_date):
    """
    Gather the trading symbols confirmed to be REITs or InvITs on NSE, from Dhan's explicit 'InvITU' and 'REIT' instrument types.

    Sourced from Dhan rather than Kotak because a first attempt cross-referencing Kotak's 'IV' and 'RR' groups surfaced an apparent spelling mismatch against Fyers ("IRBIT" versus "IRBINVIT") that turned out, on inspection of Dhan's fuller list, to be two genuinely distinct trusts rather than one broker's alias for the other. Dhan's underlying_symbol matched Fyers' own ticker exactly once compared directly, confirming it as the more reliable shared spelling here.

    Args:
        connection (sqlalchemy.engine.Connection): An open database connection.
        mapping_date (datetime.date): The raw snapshot date to draw from.

    Returns:
        set[str]: NSE trading symbols confirmed to be investment trusts.
    """
    rows = connection.execute(
        text(
            "SELECT underlying_symbol AS symbol FROM dhan.instruments "
            "WHERE download_date = :d AND exch_id = 'NSE' AND segment = 'E' "
            "AND instrument = 'EQUITY' AND instrument_type IN ('InvITU', 'REIT')"
        ),
        {"d": mapping_date},
    ).all()
    symbols = set()
    for row in rows:
        if row.symbol:
            symbols.add(row.symbol)
    return symbols


def known_nse_fixed_income_symbols(connection, mapping_date):
    """
    Gather the trading symbols confirmed to be bonds, treasury bills, or sovereign gold bonds on NSE, from Dhan's ISIN-verified fixed-income instrument types plus the equivalent 'Other'-tagged series.

    Unlike known_bse_fixed_income_symbols, this must not be used to exclude rows from an equities build: Dhan's underlying_symbol for a corporate bond or NCD row is the issuer's name, which legitimately collides with that same issuer's real equity ticker. Companies like MOTHERSON, CHOLAFIN, and ELECTCAST appear here purely because they also have listed NCDs, not because their equity rows are mislabeled. This set is only meant for building the fixed income segment itself, never as an equities cross-reference.

    Args:
        connection (sqlalchemy.engine.Connection): An open database connection.
        mapping_date (datetime.date): The raw snapshot date to draw from.

    Returns:
        set[str]: NSE trading symbols confirmed to be fixed income.
    """
    rows = connection.execute(
        text(
            "SELECT underlying_symbol AS symbol FROM dhan.instruments "
            "WHERE download_date = :d AND exch_id = 'NSE' AND segment = 'E' "
            "AND instrument = 'EQUITY' AND (instrument_type IN "
            "('DBT', 'DEB', 'TB', 'GB', 'CB', 'PTC') "
            "OR (instrument_type = 'Other' AND series IN ('GB', 'SG', 'TB', 'N0', 'N2')))"
        ),
        {"d": mapping_date},
    ).all()
    symbols = set()
    for row in rows:
        if row.symbol:
            symbols.add(row.symbol)
    return symbols


def known_nse_etf_symbols(connection, mapping_date):
    """
    Gather the trading symbols confirmed to be genuine, continuously quoted NSE exchange traded funds.

    This is narrower than known_nse_fund_symbols, which also pools the STAR mutual fund platform scheme codes that share the same INF-prefixed ISIN convention. On NSE the contamination is not separable by any single broker's tag — Dhan's own 'MF' and 'ETF' instrument type mixes both under one tag. The real discriminator, verified live, is each broker's own plain-equity series or group: Dhan's series 'EQ' within its 'MF' and 'ETF' instrument type exactly matches Shoonya's scheme-code rows as the complement, exactly matches Fyers' dedicated exchange_instrument_type 9 bucket at 349 symbols both ways, and Kotak's and Wisdom Capital's INF-prefixed rows within their own plain-equity groups reconfirm the identical 349. Stoxkart adds two further genuine tickers absent from every other ISIN-bearing broker, both target-maturity bond ETFs, confirmed also present under the same bare names in Flattrade's plain equity listing, which has no ISIN of its own to self-verify with. Groww reconfirms the same set plus a couple only it carries with a stray "-EQ" suffix, which is stripped so every broker's contribution lands on the same bare-ticker convention.

    Args:
        connection (sqlalchemy.engine.Connection): An open database connection.
        mapping_date (datetime.date): The raw snapshot date to draw from.

    Returns:
        set[str]: NSE trading symbols confirmed to be exchange traded funds.
    """
    symbols = set()

    dhan_rows = connection.execute(
        text(
            "SELECT underlying_symbol AS symbol FROM dhan.instruments "
            "WHERE download_date = :d AND exch_id = 'NSE' AND segment = 'E' "
            "AND instrument_type IN ('MF', 'ETF') AND series = 'EQ'"
        ),
        {"d": mapping_date},
    ).all()
    for row in dhan_rows:
        if row.symbol:
            symbols.add(row.symbol)

    fyers_rows = connection.execute(
        text(
            "SELECT symbol_ticker AS symbol FROM fyers.instruments "
            "WHERE download_date = :d AND exchange = '10' AND segment = '10' "
            "AND exchange_instrument_type = '9'"
        ),
        {"d": mapping_date},
    ).all()
    for row in fyers_rows:
        if row.symbol:
            bare_ticker = row.symbol.replace("NSE:", "").rsplit("-", 1)[0]
            symbols.add(bare_ticker)

    equity_group_queries = [
        (
            "SELECT regexp_replace(ptrdsymbol, '-[A-Z0-9]+$', '') AS symbol "
            "FROM kotak.instruments WHERE download_date = :d AND pexchseg = 'nse_cm' "
            "AND pgroup IN ('EQ','SM','BE','ST','BZ','SZ','E1','IT','W1') "
            "AND pisin LIKE 'INF%'"
        ),
        (
            "SELECT symbol FROM stoxkart.instruments WHERE download_date = :d "
            "AND exchange = 'NSE' AND series IN "
            "('EQ','SM','BE','ST','BZ','SZ','E1','IT','W1','T0','P1','X1') "
            "AND isin_code LIKE 'INF%'"
        ),
        (
            "SELECT name AS symbol FROM wisdom_capital.instruments "
            "WHERE download_date = :d AND exchangesegment = 'NSECM' AND series IN "
            "('EQ','SM','BE','ST','BZ','SZ','E1','IT','W1','T0') AND isin LIKE 'INF%'"
        ),
        (
            "SELECT trading_symbol AS symbol FROM groww.instruments "
            "WHERE download_date = :d AND exchange = 'NSE' AND segment = 'CASH' "
            "AND instrument_type = 'EQ' AND series = 'EQ' AND isin LIKE 'INF%'"
        ),
    ]
    for query in equity_group_queries:
        rows = connection.execute(text(query), {"d": mapping_date}).all()
        for row in rows:
            if row.symbol:
                symbols.add(row.symbol)

    stripped_symbols = set()
    for symbol in symbols:
        if symbol.endswith("-EQ"):
            stripped_symbols.add(symbol[:-3])
        else:
            stripped_symbols.add(symbol)
    return stripped_symbols


def known_bse_etf_symbols(connection, mapping_date):
    """
    Gather the trading symbols confirmed to be genuine, continuously quoted BSE exchange traded funds.

    This is not the much larger BSE STAR mutual fund platform scheme-code universe — a purchase and redemption channel settled at NAV, not a traded security — which contaminates every ISIN-based or instrument-type-based signal for this segment on its own. Two independent sources are unioned.

    The first is the three brokers whose BSE fund group carries only real exchange traded funds: Flattrade's 'E' group, Shoonya's 'E' group, and Kotak's 'E' group minus rows whose description starts with 'INAV', which are indicative-NAV reference rows rather than real funds. That source alone finds only 43 rows, all Gold and Silver, which would suggest no broad-market equity-index BSE fund exists as a distinct listing. That is only true of the dedicated fund tag.

    The second source is every broker's own name or description field matched against '%etf%', excluding 'INAV' rows, kept only where two or more independent brokers agree on the same symbol. A single broker's match is too easy to trip on a coincidental substring — Wisdom Capital's own "JETFREFT" style false positive was a real freight company whose name merely contains "ETF", with a plain 'INE'-prefixed ISIN rather than a fund ISIN — while every genuine two-broker match carried an 'INF'-prefixed fund-family ISIN with zero exceptions when checked against Dhan's own ISIN column. This second source confirmed that broad-market equity-index funds such as SENSEXBEES, CPSEETF, and HDFCSENSEX are real, exchange-listed BSE listings sitting inside brokers' plain equity series rather than a dedicated fund tag, bringing the verified total to 276.

    Args:
        connection (sqlalchemy.engine.Connection): An open database connection.
        mapping_date (datetime.date): The raw snapshot date to draw from.

    Returns:
        set[str]: BSE trading symbols confirmed to be exchange traded funds.
    """
    symbols = set()
    fund_group_queries = [
        (
            "SELECT tradingsymbol AS symbol FROM flattrade.instruments "
            "WHERE download_date = :d AND exchange = 'BSE' AND instrument = 'E'"
        ),
        (
            "SELECT tradingsymbol AS symbol FROM shoonya.instruments "
            "WHERE download_date = :d AND exchange = 'BSE' AND instrument = 'E'"
        ),
        (
            "SELECT ptrdsymbol AS symbol FROM kotak.instruments "
            "WHERE download_date = :d AND pexchseg = 'bse_cm' AND pgroup = 'E' "
            "AND pdesc NOT LIKE 'INAV%'"
        ),
    ]
    for query in fund_group_queries:
        rows = connection.execute(text(query), {"d": mapping_date}).all()
        for row in rows:
            if row.symbol:
                symbols.add(row.symbol)

    name_queries = [
        (
            "SELECT underlying_symbol AS symbol FROM dhan.instruments "
            "WHERE download_date = :d AND exch_id = 'BSE' AND segment = 'E' "
            "AND display_name ILIKE '%etf%' AND underlying_symbol NOT ILIKE '%INAV%'"
        ),
        (
            "SELECT ptrdsymbol AS symbol FROM kotak.instruments "
            "WHERE download_date = :d AND pexchseg = 'bse_cm' "
            "AND pdesc ILIKE '%etf%' AND ptrdsymbol NOT ILIKE '%INAV%'"
        ),
        (
            "SELECT trading_symbol AS symbol FROM groww.instruments "
            "WHERE download_date = :d AND exchange = 'BSE' AND segment = 'CASH' "
            "AND name ILIKE '%etf%' AND trading_symbol NOT ILIKE '%INAV%'"
        ),
        (
            "SELECT symbol FROM stoxkart.instruments "
            "WHERE download_date = :d AND exchange = 'BSE' "
            "AND symbol_description ILIKE '%etf%' AND symbol NOT ILIKE '%INAV%'"
        ),
        (
            "SELECT name AS symbol FROM wisdom_capital.instruments "
            "WHERE download_date = :d AND exchangesegment = 'BSECM' "
            "AND description ILIKE '%etf%' AND name NOT ILIKE '%INAV%'"
        ),
        (
            "SELECT tradingsymbol AS symbol FROM zerodha.instruments "
            "WHERE download_date = :d AND exchange = 'BSE' AND segment = 'BSE' "
            "AND name ILIKE '%etf%' AND tradingsymbol NOT ILIKE '%INAV%'"
        ),
        (
            "SELECT underlying_symbol AS symbol FROM fyers.instruments "
            "WHERE download_date = :d AND exchange = '12' AND segment = '10' "
            "AND symbol_details ILIKE '%etf%' AND underlying_symbol NOT ILIKE '%INAV%'"
        ),
        (
            "SELECT trading_symbol AS symbol FROM indmoney.instruments "
            "WHERE download_date = :d AND exch = 'BSE' "
            "AND symbol_name ILIKE '%etf%' AND trading_symbol NOT ILIKE '%INAV%'"
        ),
    ]
    votes = {}
    for query in name_queries:
        rows = connection.execute(text(query), {"d": mapping_date}).all()
        contributing_symbols = set()
        for row in rows:
            if row.symbol:
                contributing_symbols.add(row.symbol)
        for symbol in contributing_symbols:
            votes[symbol] = votes.get(symbol, 0) + 1
    for symbol, count in votes.items():
        if count >= 2:
            symbols.add(symbol)
    return symbols


def security_id_to_isin(connection, mapping_date):
    """
    Build a mapping from exchange-assigned security id to ISIN, drawn from every ISIN-bearing broker's BSE and NSE cash-segment rows.

    The key is the plain exchange-assigned security id that Dhan's security_id, Kotak's psymbol, Fyers' scrip_code, Groww's exchange_token, Stoxkart's token, and Wisdom Capital's exchangeinstrumentid all draw from — the same underlying scheme, not a broker-specific token. This was confirmed live: NSE RELIANCE resolves to 2885 in Dhan, Shoonya's own token, and Zerodha's own exchange_token alike, a sample of Dhan corporate bonds resolved to the identical id plus an exactly matching ticker in Shoonya's and Zerodha's own raw files, and the full fixed-income bucket of all three ISIN-less brokers matched completely through this lookup with zero unresolved rows.

    The mapping backfills an ISIN for Zerodha, Shoonya, and IND Money, whose raw files carry no ISIN column at all, so their fixed-income rows can still be identified by ISIN — which is the only identity India's one-off corporate bonds and NCDs have that reconciles across brokers, their tickers being too inconsistent to match on.

    First-seen wins on a same-id disagreement across sources, checked in the order the sources are listed. This was confirmed live to affect only 21 of 35,628 entries, each either a stray index name sitting in one broker's isin-like column or a same-security ISIN one broker's file had not caught up on, never a genuinely different security under the same id.

    Args:
        connection (sqlalchemy.engine.Connection): An open database connection.
        mapping_date (datetime.date): The raw snapshot date to draw from.

    Returns:
        dict[str, str]: Mapping of security id to ISIN.
    """
    sources = [
        (
            "dhan",
            "security_id",
            "isin",
            "exch_id IN ('BSE', 'NSE') AND segment = 'E'",
        ),
        (
            "kotak",
            "psymbol",
            "pisin",
            "pexchseg IN ('bse_cm', 'nse_cm')",
        ),
        (
            "fyers",
            "scrip_code",
            "isin",
            "exchange IN ('10', '12') AND segment = '10'",
        ),
        (
            "groww",
            "exchange_token",
            "isin",
            "exchange IN ('BSE', 'NSE') AND segment = 'CASH' AND instrument_type <> 'IDX'",
        ),
        (
            "stoxkart",
            "token",
            "isin_code",
            "exchange IN ('BSE', 'NSE')",
        ),
        (
            "wisdom_capital",
            "exchangeinstrumentid",
            "isin",
            "exchangesegment IN ('BSECM', 'NSECM')",
        ),
    ]
    mapping = {}
    for broker, token_column, isin_column, where_clause in sources:
        rows = connection.execute(
            text(
                f"SELECT {token_column}, {isin_column} FROM {broker}.instruments "
                f"WHERE download_date = :d AND {where_clause} "
                f"AND {isin_column} IS NOT NULL AND {isin_column} <> ''"
            ),
            {"d": mapping_date},
        ).all()
        for token, isin in rows:
            mapping.setdefault(str(token), isin)
    return mapping


def normalize_index_name(name):
    """
    Reduce an index name to uppercase alphanumerics, so that two brokers spelling one index differently collide.

    Args:
        name (str): The raw index name from a broker table.

    Returns:
        str: The name with every non-alphanumeric character removed and uppercased.
    """
    return re.sub(r"[^A-Z0-9]", "", str(name or "").upper())


def equity_index_lookup(connection, mapping_date):
    """
    Build the map from a normalized NSE equity index name to the canonical spelling to store it under.

    The canonical spellings are read from the instruments already mapped into unified.instruments, so index normalization needs no separate crosswalk table. It relies on the fixed processing order in the daily job: the index-listing brokers write their nse_equity_indices rows before the normalizing brokers read this map.

    The date test asks whether an index was known as of the mapping date, rather than whether it was last seen on it. Those are the same thing only while the mapping date is the most recent one mapped. Testing last seen alone makes the answer depend on what has been mapped since, so re-running one broker over a past date would find nothing here and quietly stop normalizing its index names.

    Widening that test brings a second requirement with it. Once rows from several dates are in scope, one normalized name can have more than one spelling behind it, and the map has to choose. It takes the earliest established spelling, breaking ties on the spelling itself, so the answer is the same every run rather than depending on the order the database happens to return rows in. Building this map here rather than in each adapter is what makes that guarantee hold for all of them at once.

    Args:
        connection (sqlalchemy.engine.Connection): An open database connection.
        mapping_date (datetime.date): The mapping date whose master rows to draw from.

    Returns:
        dict[str, str]: Normalized index name to the canonical symbol.
    """
    rows = connection.execute(
        text(
            f"SELECT symbol FROM {tables.MASTER} "
            "WHERE segment = 'nse_equity_indices' "
            "AND first_seen_date <= :d AND last_seen_date >= :d "
            "ORDER BY first_seen_date ASC, symbol ASC"
        ),
        {"d": mapping_date},
    ).all()
    lookup = {}
    for row in rows:
        if not row.symbol:
            continue
        key = normalize_index_name(row.symbol)
        if key not in lookup:
            lookup[key] = row.symbol
    return lookup
