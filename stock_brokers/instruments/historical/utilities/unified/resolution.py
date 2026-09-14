"""
Find the unified instrument behind each of a broker's stored price series.

A series is resolved once, as a whole, rather than bar by bar. Its bars go back years before the
first mapping date, so no date-by-date lookup could place them; what can be known is which
instruments the series' token has pointed at over the mapping dates there are, and the choice
between those is made here.

The evidence is tried in order of strength:

1. **The broker's own mapping** (`broker_mapping`). The token's spans in unified.broker_mappings,
   restricted to the segments the identifier allows. One candidate settles it. Several are
   narrowed in three ways, in turn:

   - A *transient* is dropped: a candidate seen on fewer dates, entirely inside another's span.
     On 2026-08-12 only zerodha's file was mapped, and without other brokers to cross-reference, its
     exchange traded funds and bonds were filed as uncategorised for that one day, under
     identities that exist on no other date.
   - A *consensus* picks between candidates seen side by side: the one other brokers map the same
     exchange token to. flattrade's file keeps a stale row for DSP's IT ETF under its old symbol
     ITETFADD beside the current ITADD, both on token 17207, while every other broker maps 17207 to
     ITADD alone.
   - *Sequential* candidates, one ending before the next begins, split the series in time at the
     boundary; bars from before the first mapping date belong to the earliest.

   Anything still unresolved is `ambiguous`, and reported rather than guessed.

2. **Other brokers' mappings of the exchange token** (`exchange_token`), when the broker never
   mapped the token at all. flattrade maps a symbol's EQ row and not its BE row, so its BE series -
   566 of them in daily bars - have no mapping of their own, while the exchange token, shared by
   every broker's NSE and BSE files, names the instrument.

3. **The trading symbol** (`raw_symbol`), matched against unified.instruments in the allowed
   segments, only when it matches exactly one instrument - counting an uncategorised twin of a
   classified instrument as no match, since that is a row a broker could not classify.

Resolution follows unified.instruments's idea of identity, in which the symbol is part of what an
instrument is. A company that changes its symbol is therefore two instruments, and its series is
split at the rename: MANBRO before 2026-09-03, KDGREEN from then on.
"""

import datetime
from collections import namedtuple

from sqlalchemy import text

from stock_brokers.instruments.historical.base import INDIA_TIMEZONE
from stock_brokers.instruments.historical.utilities.orchestrator import downloader_for
from stock_brokers.instruments.mapping.utilities.resolution import MappingResolver
from stock_brokers.instruments.historical.utilities.unified import tables

# One instrument a series belongs to, for the part of its history between `valid_from` and
# `valid_to` (None meaning unbounded). A series split between sequential instruments has one
# Resolution per instrument; an unresolved series has one with instrument_id None.
Resolution = namedtuple("Resolution", [
    "identifier", "instrument_id", "exchange", "segment", "symbol", "resolved_by", "status",
    "status_reason", "mapping_first_date", "mapping_last_date", "valid_from", "valid_to",
])

# Brokers whose NSE and BSE token is the exchange's own token, and so can vouch for one.
EXCHANGE_TOKEN_BROKERS = ("dhan", "indmoney", "shoonya", "flattrade", "kotak", "groww", "stoxkart",
                          "wisdom_capital")

# Kite's low byte for each exchange and family, which with the exchange token rebuilds the Kite token.
ZERODHA_SEGMENT_CODES = {
    ("nse", "cash"): (1,),
    ("bse", "cash"): (4,),
    ("nse", "derivative"): (2, 3, 12),
    ("bse", "derivative"): (5, 6),
    ("mcx", "derivative"): (7,),
}

# A consensus needs at least this many other brokers behind the winner.
MINIMUM_CONSENSUS = 2

def india_midnight(day):
    """
    Midnight India time at the start of a date.

    Args:
        day (datetime.date): The date.

    Returns:
        datetime.datetime: A timezone aware timestamp.
    """
    return datetime.datetime(day.year, day.month, day.day, tzinfo=INDIA_TIMEZONE)

def family_of(segments):
    """
    The family a SeriesContext's segments describe, for rebuilding Kite tokens.

    Args:
        segments (tuple[str] | None): Prefixed segments.

    Returns:
        str | None: "cash" or "derivative", or None when the segments are neither.
    """
    if not segments:
        return None
    if any(segment.endswith(("_futures", "_options")) for segment in segments):
        return "derivative"
    if any(segment.endswith(("_equities", "_exchange_traded_funds")) for segment in segments):
        return "cash"
    return None

class SeriesResolver:
    """
    Resolves broker price series to unified instruments.

    Attributes:
        mapping_resolver (MappingResolver): The look-ups over the mapped tables.
        engine (sqlalchemy.engine.Engine): The engine those look-ups use.
    """

    def __init__(self, mapping_resolver=None):
        """
        Build the resolver.

        Args:
            mapping_resolver (MappingResolver | None): An existing resolver to share, or None to build one.

        Returns:
            None: This function returns nothing.
        """
        self.mapping_resolver = mapping_resolver or MappingResolver()
        self.engine = self.mapping_resolver.engine

    def resolve(self, broker, identifiers):
        """
        Resolve a broker's series.

        Args:
            broker (str): The broker name, for example "flattrade".
            identifiers (list[str]): Values of `instrument_token` in the broker's price table.

        Returns:
            dict: Mapping of identifier to a list of Resolution, never empty.
        """
        candles = downloader_for(broker)
        contexts = {}
        for identifier in identifiers:
            contexts[identifier] = candles.series_context(identifier)

        # Series that share segments and match column are looked up together.
        groups = {}
        for identifier, context in contexts.items():
            key = (tuple(context.segments) if context.segments else None, context.match_on)
            groups.setdefault(key, []).append(identifier)

        resolved = {}
        for (segments, match_on), members in groups.items():
            tokens = sorted({contexts[identifier].broker_token for identifier in members})
            spans = self.mapping_resolver.identity_spans(broker, tokens, segments, match_on)
            votes = self.exchange_token_votes(broker, [contexts[identifier] for identifier in members])
            unresolved = []
            for identifier in members:
                context = contexts[identifier]
                candidates = spans.get(context.broker_token, [])
                if candidates:
                    resolved[identifier] = self.choose(identifier, candidates,
                                                       votes.get(context.exchange_token, {}))
                else:
                    unresolved.append(identifier)
            for identifier in unresolved:
                context = contexts[identifier]
                resolved[identifier] = self.fall_back(identifier, context,
                                                      votes.get(context.exchange_token, {}))
        return resolved

    def choose(self, identifier, candidates, votes):
        """
        Pick between the instruments a series' own token has been mapped to.

        Args:
            identifier (str): The series identifier.
            candidates (list[dict]): The token's spans, as `identity_spans` returns them.
            votes (dict): Other brokers' support per instrument_id for the exchange token.

        Returns:
            list[Resolution]: One Resolution, or several for a sequential split.
        """
        if len(candidates) == 1:
            return [self.resolution(identifier, candidates[0], "broker_mapping")]

        lasting = []
        for candidate in candidates:
            contained = False
            for other in candidates:
                if other is candidate:
                    continue
                if (other["first_mapping_date"] <= candidate["first_mapping_date"]
                        and other["last_mapping_date"] >= candidate["last_mapping_date"]
                        and other["mapping_dates"] > candidate["mapping_dates"]):
                    contained = True
                    break
            if not contained:
                lasting.append(candidate)
        if len(lasting) == 1:
            dropped = len(candidates) - 1
            return [self.resolution(identifier, lasting[0], "broker_mapping",
                                    reason=f"{dropped} transient mapping(s) ignored")]

        ranked = sorted(lasting, key=lambda candidate: votes.get(candidate["instrument_id"], 0), reverse=True)
        best = votes.get(ranked[0]["instrument_id"], 0)
        runner_up = votes.get(ranked[1]["instrument_id"], 0)
        if best >= MINIMUM_CONSENSUS and best > runner_up:
            return [self.resolution(identifier, ranked[0], "broker_mapping",
                                    reason=f"chosen by {best} other brokers over {runner_up}")]

        ordered = sorted(lasting, key=lambda candidate: candidate["first_mapping_date"])
        sequential = True
        for earlier, later in zip(ordered, ordered[1:]):
            if earlier["last_mapping_date"] >= later["first_mapping_date"]:
                sequential = False
                break
        if sequential:
            resolutions = []
            for position, candidate in enumerate(ordered):
                valid_from = None
                valid_to = None
                if position > 0:
                    valid_from = india_midnight(candidate["first_mapping_date"])
                if position < len(ordered) - 1:
                    valid_to = india_midnight(ordered[position + 1]["first_mapping_date"])
                resolutions.append(self.resolution(identifier, candidate, "broker_mapping",
                                                   reason=f"split across {len(ordered)} sequential instruments",
                                                   valid_from=valid_from, valid_to=valid_to))
            return resolutions

        names = ", ".join(f"{candidate['segment']}:{candidate['symbol']}" for candidate in lasting)
        return [Resolution(identifier, None, None, None, None, "broker_mapping", "ambiguous",
                           f"token mapped to {len(lasting)} instruments at once: {names}",
                           None, None, None, None)]

    def fall_back(self, identifier, context, votes):
        """
        Resolve a series whose own token was never mapped.

        Args:
            identifier (str): The series identifier.
            context (SeriesContext): What the identifier says about itself.
            votes (dict): Other brokers' support per instrument_id for the exchange token.

        Returns:
            list[Resolution]: One Resolution, unresolved if nothing matched.
        """
        if votes:
            ranked = sorted(votes.items(), key=lambda item: item[1], reverse=True)
            best = ranked[0][1]
            runner_up = ranked[1][1] if len(ranked) > 1 else 0
            if best >= MINIMUM_CONSENSUS and best > runner_up:
                instrument = self.instrument(ranked[0][0])
                return [self.resolution(identifier, instrument, "exchange_token",
                                        reason=f"exchange token {context.exchange_token} mapped by {best} brokers")]

        if context.symbol and context.segments:
            matches = self.symbol_matches(context.exchange, context.segments, context.symbol)
            # An uncategorised twin is a row some broker could not classify, not a second security:
            # NSE's temporary BE token for ORICONENT, 10163, is mapped only by stoxkart, which files
            # BE rows as uncategorised. A classified match outranks it.
            classified = [match for match in matches if not match["segment"].endswith("uncategorised")]
            if len(classified) == 1:
                matches = classified
            if len(matches) == 1:
                return [self.resolution(identifier, matches[0], "raw_symbol",
                                        reason=f"symbol {context.symbol}")]
            if len(matches) > 1:
                return [Resolution(identifier, None, None, None, None, "raw_symbol", "ambiguous",
                                   f"symbol {context.symbol} matches {len(matches)} instruments",
                                   None, None, None, None)]

        return [Resolution(identifier, None, None, None, None, None, "rejected",
                           "no mapping, exchange token or symbol match", None, None, None, None)]

    def exchange_token_votes(self, broker, contexts):
        """
        Count, for each exchange token, how many other brokers map it to each instrument.

        Args:
            broker (str): The broker whose series are being resolved, which does not vote.
            contexts (list[SeriesContext]): Series sharing one set of segments.

        Returns:
            dict: exchange_token to {instrument_id: number of distinct brokers}.
        """
        with_tokens = [context for context in contexts if context.exchange_token and context.segments]
        if not with_tokens:
            return {}
        segments = list(with_tokens[0].segments)
        exchange_tokens = sorted({context.exchange_token for context in with_tokens})

        # Kite tokens rebuilt from the exchange token, so the lookup stays on the token index.
        zerodha_tokens = {}
        codes = ZERODHA_SEGMENT_CODES.get((with_tokens[0].exchange, family_of(segments)), ())
        for exchange_token in exchange_tokens:
            if not exchange_token.isdigit():
                continue
            for code in codes:
                zerodha_tokens[str(int(exchange_token) << 8 | code)] = exchange_token

        voters = [name for name in EXCHANGE_TOKEN_BROKERS if name != broker]
        statement = text(
            "SELECT b.broker, b.broker_token, b.instrument_id "
            f"FROM {tables.BROKER_MAPPINGS} b "
            f"JOIN {tables.MASTER} m ON m.instrument_id = b.instrument_id "
            "WHERE m.segment = ANY(:segments) AND ("
            "  (b.broker = ANY(:voters) AND b.broker_token = ANY(:exchange_tokens)) "
            "  OR (b.broker = 'zerodha' AND :include_zerodha AND b.broker_token = ANY(:zerodha_tokens))) "
            "GROUP BY b.broker, b.broker_token, b.instrument_id"
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement, {
                "segments": segments,
                "voters": voters,
                "exchange_tokens": exchange_tokens,
                "include_zerodha": broker != "zerodha",
                "zerodha_tokens": list(zerodha_tokens),
            }).all()

        supporters = {}
        for row in rows:
            if row.broker == "zerodha":
                exchange_token = zerodha_tokens[row.broker_token]
            else:
                exchange_token = row.broker_token
            supporters.setdefault(exchange_token, {}).setdefault(str(row.instrument_id), set()).add(row.broker)

        votes = {}
        for exchange_token, instruments in supporters.items():
            votes[exchange_token] = {instrument_id: len(names) for instrument_id, names in instruments.items()}
        return votes

    def instrument(self, instrument_id):
        """
        One instrument's identity and its span across every broker's mappings.

        Args:
            instrument_id (str): The unified id.

        Returns:
            dict: The keys `identity_spans` returns.
        """
        with self.engine.connect() as connection:
            row = connection.execute(text(
                "SELECT m.instrument_id, m.exchange, m.segment, m.shape, m.symbol, "
                "  m.first_seen_date AS first_mapping_date, m.last_seen_date AS last_mapping_date "
                f"FROM {tables.MASTER} m WHERE m.instrument_id = :instrument_id"
            ), {"instrument_id": instrument_id}).one()
        return dict(row._mapping, instrument_id=str(row.instrument_id), mapping_dates=None)

    def symbol_matches(self, exchange, segments, symbol):
        """
        Every instrument with this exact symbol in the allowed segments, on any date.

        Args:
            exchange (str): The canonical exchange.
            segments (tuple[str]): The allowed prefixed segments.
            symbol (str): The trading symbol without its series suffix.

        Returns:
            list[dict]: The keys `identity_spans` returns.
        """
        with self.engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT m.instrument_id, m.exchange, m.segment, m.shape, m.symbol, "
                "  m.first_seen_date AS first_mapping_date, m.last_seen_date AS last_mapping_date "
                f"FROM {tables.MASTER} m "
                "WHERE m.exchange = :exchange AND m.segment = ANY(:segments) AND upper(m.symbol) = :symbol"
            ), {"exchange": exchange, "segments": list(segments), "symbol": symbol.upper()}).all()
        return [dict(row._mapping, instrument_id=str(row.instrument_id), mapping_dates=None) for row in rows]

    @staticmethod
    def resolution(identifier, candidate, resolved_by, reason=None, valid_from=None, valid_to=None):
        """
        An active Resolution for a chosen candidate.

        Args:
            identifier (str): The series identifier.
            candidate (dict): The chosen instrument, as `identity_spans` returns it.
            resolved_by (str): How it was found.
            reason (str | None): Why, when the choice was not the only candidate.
            valid_from (datetime.datetime | None): The start of the part of the series it owns.
            valid_to (datetime.datetime | None): The end of that part, exclusive.

        Returns:
            Resolution: The resolution.
        """
        return Resolution(identifier, candidate["instrument_id"], candidate["exchange"], candidate["segment"],
                          candidate["symbol"], resolved_by, "active", reason,
                          candidate["first_mapping_date"], candidate["last_mapping_date"], valid_from, valid_to)
