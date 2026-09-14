"""
Streamlit app for trying the REST API's session, detail, order book, portfolio and instrument endpoints by hand.

Start the API first, then the app:

    bin/rest-api                                   # or: bin/rest-api --dev
    bin/rest-api-app                               # add --lan to open it from another machine

Then open http://127.0.0.1:8501 in a browser.

The sidebar holds the API address, the api key and secret, and the access token the app is using.
The key and secret can be typed in or loaded from the `unified_broker_interface` document in the
MongoDB `settings` collection. A successful connect stores the returned token, and every other call
sends it - unless the sidebar says to send none or a deliberately wrong one, which is how the 401
paths are tried.

Every call shows its status, time taken and response body, and is added to a request log at the
bottom of the page. The page calls the session, detail, instrument and portfolio endpoints and the two
order book reads, `GET /api/orders/details` and `GET /api/orders/trades`.
"""

import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st

# `streamlit run` puts only this file's directory on sys.path, not the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utilities.configurations import api_configuration  # noqa: E402
from stock_brokers.instruments.mapping.utilities.segments import CANONICAL_SEGMENTS, segment_value  # noqa: E402

REQUEST_TIMEOUT_SECONDS = 60

# The detail endpoints: tab label, path, and what the list is.
DETAIL_ENDPOINTS = [
    ("Users", "/api/users/details", "user profiles from `user_details`"),
    ("Brokers", "/api/brokers/details", "broker details from `broker_details`"),
    ("Exchanges", "/api/exchanges/details", "exchange details from `exchange_details`"),
]

def load_stored_credentials():
    """
    The api key and secret from the `unified_broker_interface` document in `settings`, or None.
    """
    from utilities.configurations import get_mongo_db

    settings = get_mongo_db()['settings'].find_one({'broker_name': 'unified_broker_interface'}, {'_id': 0})
    if not settings:
        return None
    return settings.get('api_key', ''), settings.get('api_secret', '')

def token_header():
    """
    The `access-token` header to send, according to the sidebar's token mode.
    """
    mode = st.session_state.token_mode
    if mode == "No token":
        return {}
    if mode == "Wrong token":
        return {'access-token': str(uuid.uuid4())}
    token = st.session_state.access_token
    return {'access-token': token} if token else {}

def preview_array(response, max_rows):
    """
    The first rows of a streamed JSON array, read only as far as they need, and whether there were more.

    A stream such as `/api/instruments/master?exchange=all&segment=all` runs to over a hundred megabytes,
    so it is decoded object by object as the chunks arrive and the connection is closed once `max_rows`
    objects have been read.

    - `response` is a `requests` response opened with `stream=True`.
    - `max_rows` is how many objects to keep.
    """
    decoder = json.JSONDecoder()
    buffer = ""
    rows = []
    started = False
    for chunk in response.iter_content(64 * 1024, decode_unicode=True):
        buffer += chunk
        position = 0
        while True:
            while position < len(buffer) and buffer[position] in " \n\r\t,":
                position += 1
            if not started:
                if position < len(buffer) and buffer[position] == "[":
                    started = True
                    position += 1
                    continue
                break
            if position < len(buffer) and buffer[position] == "]":
                return rows, False
            try:
                row, end = decoder.raw_decode(buffer, position)
            except ValueError:
                break
            rows.append(row)
            position = end
            if len(rows) >= max_rows:
                response.close()
                return rows, True
        buffer = buffer[position:]
    return rows, False

def call(method, path, headers=None, params=None, stream_rows=None):
    """
    Send one request, record it in the log, and return a result dict for display.

    - `method` is the HTTP method.
    - `path` is the endpoint path, such as `/api/session/status`.
    - `headers` are the request headers.
    - `params` are the query parameters.
    - `stream_rows` reads a streamed JSON array only this far, for the streaming endpoints.
    """
    url = st.session_state.base_url.rstrip('/') + path
    headers = headers or {}
    params = {name: value for name, value in (params or {}).items() if value not in (None, "")}
    started = time.perf_counter()
    try:
        response = requests.request(method, url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS,
                                    stream=stream_rows is not None)
        truncated = False
        if stream_rows is not None and response.status_code == 200:
            body, truncated = preview_array(response, stream_rows)
        else:
            try:
                body = response.json()
            except ValueError:
                body = response.text
        elapsed_ms = (time.perf_counter() - started) * 1000
        result = {'status': response.status_code, 'elapsed_ms': elapsed_ms, 'body': body, 'error': None,
                  'truncated': truncated, 'headers': {name: value for name, value in response.headers.items()
                                                      if name.lower().startswith('x-')}}
    except requests.RequestException as error:
        elapsed_ms = (time.perf_counter() - started) * 1000
        result = {'status': None, 'elapsed_ms': elapsed_ms, 'body': None, 'error': str(error)}

    # Header values are logged by name only, so the secret never lands in the log.
    st.session_state.log.insert(0, {
        'time': datetime.now().strftime("%H:%M:%S"),
        'method': method,
        'path': path + (f"?{'&'.join(f'{name}={value}' for name, value in params.items())}" if params else ""),
        'headers sent': ', '.join(sorted(headers)) or '-',
        'status': result['status'] if result['status'] is not None else 'no response',
        'ms': round(elapsed_ms, 1),
    })
    return result

def show_result(result, as_table=False):
    """
    Render a call's outcome: status badge, timing, and the body as JSON and optionally a table.

    - `result` is what `call` returned.
    - `as_table` also shows a list body flattened into a table.
    """
    if result['error']:
        st.error(f"No response: {result['error']}\n\nIs the API running? Start it with `bin/rest-api`.")
        return

    status = result['status']
    label = f"HTTP {status} · {result['elapsed_ms']:.0f} ms"
    if result.get('truncated'):
        label += f" · first {len(result['body'])} rows of a longer stream"
    if result.get('headers'):
        label += " · " + ", ".join(f"{name}: {value}" for name, value in result['headers'].items())
    if 200 <= status < 300:
        st.success(label)
    elif 400 <= status < 500:
        st.warning(label)
    else:
        st.error(label)

    body = result['body']
    if as_table and isinstance(body, list) and body:
        st.dataframe(pd.json_normalize(body), width="stretch")
    if isinstance(body, (dict, list)):
        st.json(body, expanded=not as_table)
    else:
        st.code(str(body))

def sidebar():
    """
    Connection settings, credentials and the token mode.
    """
    st.sidebar.header("Connection")
    st.sidebar.text_input("API base URL", key="base_url")

    st.sidebar.header("Credentials")
    if st.sidebar.button("Load from MongoDB settings", width="stretch"):
        try:
            stored = load_stored_credentials()
        except Exception as error:
            st.sidebar.error(f"Could not read MongoDB: {error}")
        else:
            if stored:
                st.session_state.api_key, st.session_state.api_secret = stored
                st.sidebar.success("Loaded.")
            else:
                st.sidebar.error("No `unified_broker_interface` document in `settings`.")
    st.sidebar.text_input("api-key", key="api_key", type="password")
    st.sidebar.text_input("api-secret", key="api_secret", type="password")

    st.sidebar.header("Access token")
    st.sidebar.text_input("access-token", key="access_token",
                          help="Filled in by a successful connect. Can be edited to try a stale token.")
    if st.session_state.expires_at:
        st.sidebar.caption(f"Expires at {st.session_state.expires_at}")
    st.sidebar.radio("Send with requests", ["Current token", "No token", "Wrong token"], key="token_mode",
                     help="'No token' and 'Wrong token' exercise the 401 responses.")

def session_tab():
    """
    Connect, status and disconnect.
    """
    st.subheader("Connect")
    st.caption("`POST /api/session/connect` with the `api-key` and `api-secret` headers. "
               "A new token replaces the one in force.")
    left, right = st.columns(2)
    connect = left.button("Connect", type="primary", width="stretch")
    wrong_secret = right.button("Connect with a wrong secret", width="stretch")
    if connect or wrong_secret:
        headers = {'api-key': st.session_state.api_key,
                   'api-secret': 'wrong-secret' if wrong_secret else st.session_state.api_secret}
        result = call('POST', '/api/session/connect', headers)
        if connect and result['status'] == 200 and isinstance(result['body'], dict):
            st.session_state.pending_token = result['body'].get('access-token', '')
            st.session_state.expires_at = result['body'].get('expires_at')
            st.session_state.last_result = ('connect', result)
            st.rerun()
        show_result(result)
    elif st.session_state.last_result and st.session_state.last_result[0] == 'connect':
        show_result(st.session_state.last_result[1])
        st.session_state.last_result = None

    st.divider()
    st.subheader("Status")
    st.caption("`GET /api/session/status` with the access token.")
    if st.button("Get status", width="stretch"):
        show_result(call('GET', '/api/session/status', token_header()))

    st.divider()
    st.subheader("Disconnect")
    st.caption("`DELETE /api/session/disconnect` revokes the token for every client.")
    if st.button("Disconnect", width="stretch"):
        result = call('DELETE', '/api/session/disconnect', token_header())
        show_result(result)

def details_tab(path, description):
    """
    One detail endpoint.

    - `path` is the endpoint path.
    - `description` says what the list holds.
    """
    st.caption(f"`GET {path}`: {description}.")
    if st.button("Send", key=f"send {path}", type="primary", width="stretch"):
        show_result(call('GET', path, token_header()), as_table=True)

def use_instrument(instrument_id):
    """
    Callback putting a picked instrument's id into the instrument field.

    - `instrument_id` is the id picked.
    """
    st.session_state.instrument_id = instrument_id

def instrument_params():
    """
    The instrument parameters to send: the id field, or the identity query when the id is empty.
    """
    if st.session_state.instrument_id.strip():
        return {'instrument_id': st.session_state.instrument_id.strip()}
    params = {}
    for pair in st.session_state.identity_query.split('&'):
        name, _, value = pair.partition('=')
        if name.strip():
            params[name.strip()] = value.strip()
    return params

def instruments_tab():
    """
    Every /api/instruments endpoint, with a search that fills in the instrument the others act on.
    """
    base = '/api/instruments'

    st.subheader("Find an instrument")
    left, middle, right, far = st.columns([1, 2, 2, 1])
    left.selectbox("exchange", ["nse", "bse", "mcx", "ncdex"], key="search_exchange")
    segments = [segment_value(st.session_state.search_exchange, bare) for bare, _ in CANONICAL_SEGMENTS]
    if st.session_state.search_segment not in segments:
        st.session_state.search_segment = segment_value(st.session_state.search_exchange, "equities")
    middle.selectbox("segment", segments, key="search_segment")
    right.text_input("q", key="search_q", placeholder="RELIANCE, NIFTY, CRUDEOIL")
    far.number_input("limit", min_value=1, max_value=200, key="search_limit")
    if st.button("Search", type="primary"):
        st.session_state.search_result = call('GET', f'{base}/search', token_header(), {
            'exchange': st.session_state.search_exchange, 'segment': st.session_state.search_segment,
            'q': st.session_state.search_q, 'limit': st.session_state.search_limit})
    found = st.session_state.search_result
    if found:
        show_result(found)
        instruments = (found['body'] or {}).get('instruments', []) if isinstance(found['body'], dict) else []
        if instruments:
            st.dataframe(pd.DataFrame(instruments), width="stretch", hide_index=True)
            labels = {f"{row.get('symbol') or row.get('underlying_symbol')} {row.get('expiry_date') or ''} "
                      f"{row.get('strike_price') or ''} {row.get('option_type') or ''} ({row['instrument_id']})": row['instrument_id']
                      for row in instruments}
            picked = st.selectbox("instrument", list(labels))
            st.button("Use this instrument", on_click=use_instrument, args=(labels[picked],))

    st.text_input("instrument_id", key="instrument_id",
                  help="The instrument the endpoints below act on. Leave empty to use the identity query instead.")
    st.text_input("or identity query", key="identity_query",
                  placeholder="exchange=nse&segment=equities&symbol=INFY")

    st.divider()
    st.subheader("Catalogue")
    columns = st.columns(3)
    if columns[0].button("Segments", width="stretch"):
        result = call('GET', f'{base}/segments', token_header())
        show_result(result)
        if result['status'] == 200:
            st.dataframe(pd.DataFrame(result['body']['segments']), width="stretch", hide_index=True)
    if columns[1].button("Details", width="stretch"):
        show_result(call('GET', f'{base}/details', token_header(), {**instrument_params(), 'date': st.session_state.details_date}))
    columns[2].text_input("details date", key="details_date", placeholder="YYYY-MM-DD, empty for today")

    master = st.columns([1, 2, 1, 1, 1])
    master[0].text_input("master exchange", key="master_exchange")
    master[1].text_input("master segment", key="master_segment")
    master[2].text_input("master date", key="master_date", placeholder="YYYY-MM-DD")
    master[3].number_input("rows to preview", min_value=1, max_value=100000, key="master_rows")
    if master[4].button("Master (stream)", width="stretch"):
        show_result(call('GET', f'{base}/master', token_header(), {
            'exchange': st.session_state.master_exchange, 'segment': st.session_state.master_segment,
            'date': st.session_state.master_date}, stream_rows=st.session_state.master_rows), as_table=True)

    st.divider()
    st.subheader("Live quote")
    st.caption("From the unified quote cache when a quote is under five minutes old or its session has closed "
               "since; otherwise from a broker. `source` says which.")
    columns = st.columns(3)
    for column, endpoint in zip(columns, ("ltp", "ohlc", "quote")):
        if column.button(f"/{endpoint}", width="stretch"):
            show_result(call('GET', f'{base}/{endpoint}', token_header(), instrument_params()))

    st.divider()
    st.subheader("Prices")
    st.caption("Adjusted for splits, bonuses and demergers only for equities, ETFs and investment trusts; "
               "everything else is as the broker served it, whatever `adjusted` says.")
    prices = st.columns(6)
    prices[0].selectbox("interval", ["day", "15minute", "20minute", "60minute", "minute", "5minute", "30minute"],
                        key="prices_interval")
    prices[1].text_input("from", key="prices_from", placeholder="YYYY-MM-DD")
    prices[2].text_input("to", key="prices_to", placeholder="YYYY-MM-DD")
    prices[3].text_input("or days", key="prices_days")
    prices[4].checkbox("adjusted", key="prices_adjusted")
    prices[5].text_input("known_as_of", key="prices_known")
    if st.button("Prices", width="stretch"):
        result = call('GET', f'{base}/prices', token_header(), {
            **instrument_params(), 'interval': st.session_state.prices_interval,
            'from': st.session_state.prices_from, 'to': st.session_state.prices_to, 'days': st.session_state.prices_days,
            'adjusted': str(st.session_state.prices_adjusted).lower(), 'known_as_of': st.session_state.prices_known})
        show_result(result)
        if result['status'] == 200 and result['body'].get('candles'):
            st.dataframe(pd.DataFrame(result['body']['candles'], columns=result['body']['columns']),
                         width="stretch", hide_index=True)

    st.divider()
    st.subheader("Ticks")
    ticks = st.columns(5)
    ticks[0].text_input("start", key="ticks_start", placeholder="2026-09-11 22:30")
    ticks[1].text_input("end", key="ticks_end", placeholder="2026-09-11 22:40")
    ticks[2].checkbox("adjusted", key="ticks_adjusted")
    ticks[3].number_input("rows to preview", min_value=1, max_value=100000, key="ticks_rows")
    if ticks[4].button("Ticks (stream)", width="stretch"):
        show_result(call('GET', f'{base}/ticks', token_header(), {
            **instrument_params(), 'start': st.session_state.ticks_start, 'end': st.session_state.ticks_end,
            'adjusted': str(st.session_state.ticks_adjusted).lower()}, stream_rows=st.session_state.ticks_rows), as_table=True)

class UnifiedDocumentView:
    """A read-only endpoint that answers with a document kept in Redis by a `bin/unified/` script.

    A subclass names its endpoint in `TITLE`, `PATH` and `DESCRIPTION` and draws the document's own tables in `draw_document`.

    Attributes:
        TITLE: The heading drawn above the endpoint's button.
        PATH: The endpoint path, such as `/api/portfolio/funds`.
        DESCRIPTION: What the document holds, drawn under the heading.
    """

    TITLE = ""
    PATH = ""
    DESCRIPTION = ""

    def draw(self) -> None:
        """Draws the endpoint's heading and button, and after a click the call's outcome and tables.

        Args:
            None.

        Returns:
            None.

        Raises:
            NotImplementedError: The subclass does not define `draw_document`.
        """
        st.subheader(self.TITLE)
        st.caption(f"`GET {self.PATH}`: {self.DESCRIPTION}.")
        clicked = st.button(
            "Send",
            key=f"send {self.PATH}",
            type="primary",
            width="stretch",
        )
        if not clicked:
            return
        result = call('GET', self.PATH, token_header())
        show_result(result, as_table=True)
        body = result['body']
        if result['error'] or not isinstance(body, dict):
            return
        self.draw_brokers(body)
        if result['status'] == 200:
            self.draw_document(body)

    def draw_brokers(self, body: dict[str, Any]) -> None:
        """Draws how each broker's data was read, which the API also sends with its 502 and 503 answers.

        Args:
            body (dict[str, Any]): The response body.

        Returns:
            None.

        Raises:
            None.
        """
        if body.get('as_of'):
            st.caption(f"Document written at {body['as_of']}.")
        brokers = body.get('brokers')
        if not brokers:
            return
        st.markdown("**Brokers**")
        st.dataframe(pd.DataFrame(brokers), width="stretch", hide_index=True)

    def draw_document(self, body: dict[str, Any]) -> None:
        """Draws the tables for the document this endpoint answers with.

        Args:
            body (dict[str, Any]): The response body of a 200 answer.

        Returns:
            None.

        Raises:
            NotImplementedError: Always, because each subclass draws its own document.
        """
        raise NotImplementedError(f'{type(self).__name__} does not draw its document')

    def draw_figures(self, label: str, figures: dict[str, Any]) -> None:
        """Draws a dictionary of figures as a two-column table, one row per figure, with nested names joined by dots.

        Args:
            label (str): The heading drawn above the table.
            figures (dict[str, Any]): The figures, which may hold nested dictionaries.

        Returns:
            None.

        Raises:
            None.
        """
        st.markdown(f"**{label}**")
        if not figures:
            st.caption("None.")
            return
        flattened = pd.json_normalize(figures).iloc[0]
        rows = []
        for name, value in flattened.items():
            rows.append(
                {
                    "figure": name,
                    "value": str(value),
                }
            )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    def draw_rows(self, label: str, rows: list[dict[str, Any]]) -> None:
        """Draws a list of records as a table, one row per record, with nested fields flattened into columns.

        Args:
            label (str): The heading drawn above the table, which also shows the row count.
            rows (list[dict[str, Any]]): The records.

        Returns:
            None.

        Raises:
            None.
        """
        st.markdown(f"**{label}** ({len(rows)})")
        if not rows:
            st.caption("None.")
            return
        st.dataframe(pd.json_normalize(rows), width="stretch", hide_index=True)


class OrderDetailsView(UnifiedDocumentView):
    """The `GET /api/orders/details` endpoint, today's orders at every broker."""

    TITLE = "Order details"
    PATH = "/api/orders/details"
    DESCRIPTION = "today's orders at every broker, from `unified:orders:orders`"

    def draw_document(self, body: dict[str, Any]) -> None:
        """Draws the order summary and one row per order.

        Args:
            body (dict[str, Any]): The response body of a 200 answer.

        Returns:
            None.

        Raises:
            None.
        """
        self.draw_figures("Summary", body.get('summary') or {})
        self.draw_rows("Orders", body.get('orders') or [])


class TradesView(UnifiedDocumentView):
    """The `GET /api/orders/trades` endpoint, today's trades at every broker."""

    TITLE = "Trades"
    PATH = "/api/orders/trades"
    DESCRIPTION = "today's trades at every broker, from `unified:orders:trades`"

    def draw_document(self, body: dict[str, Any]) -> None:
        """Draws the trade summary and one row per trade.

        Args:
            body (dict[str, Any]): The response body of a 200 answer.

        Returns:
            None.

        Raises:
            None.
        """
        self.draw_figures("Summary", body.get('summary') or {})
        self.draw_rows("Trades", body.get('trades') or [])


class FundsView(UnifiedDocumentView):
    """The `GET /api/portfolio/funds` endpoint, the account's funds summed across every broker."""

    TITLE = "Funds"
    PATH = "/api/portfolio/funds"
    DESCRIPTION = "the account's funds summed across every broker, from `unified:portfolio:funds`"

    def draw_document(self, body: dict[str, Any]) -> None:
        """Draws the balance, profit, margin and cash movement figures, and one row per segment.

        Args:
            body (dict[str, Any]): The response body of a 200 answer.

        Returns:
            None.

        Raises:
            None.
        """
        self.draw_figures("Summary", body.get('summary') or {})
        self.draw_figures("Profit and loss", body.get('pnl') or {})
        self.draw_figures("Margin breakdown", body.get('margin_breakdown') or {})
        self.draw_figures("Cash movement", body.get('cash_movement') or {})
        segment_rows = []
        for segment_name, segment_figures in (body.get('segments') or {}).items():
            row = {"segment": segment_name}
            row.update(segment_figures)
            segment_rows.append(row)
        self.draw_rows("Segments", segment_rows)


class HoldingsView(UnifiedDocumentView):
    """The `GET /api/portfolio/holdings` endpoint, the account's holdings merged across every broker."""

    TITLE = "Holdings"
    PATH = "/api/portfolio/holdings"
    DESCRIPTION = "the account's holdings merged across every broker and priced, from `unified:portfolio:holdings`"

    def draw_document(self, body: dict[str, Any]) -> None:
        """Draws the holdings summary and one row per holding.

        Args:
            body (dict[str, Any]): The response body of a 200 answer.

        Returns:
            None.

        Raises:
            None.
        """
        self.draw_figures("Summary", body.get('summary') or {})
        self.draw_rows("Holdings", body.get('holdings') or [])


class PositionsView(UnifiedDocumentView):
    """The `GET /api/portfolio/positions` endpoint, the account's open positions merged across every broker."""

    TITLE = "Positions"
    PATH = "/api/portfolio/positions"
    DESCRIPTION = "the account's open positions, net and day, merged across every broker, from `unified:portfolio:positions`"

    def draw_document(self, body: dict[str, Any]) -> None:
        """Draws the positions summary, then the net positions and the day positions as separate tables.

        Args:
            body (dict[str, Any]): The response body of a 200 answer.

        Returns:
            None.

        Raises:
            None.
        """
        self.draw_figures("Summary", body.get('summary') or {})
        self.draw_rows("Net positions", body.get('net') or [])
        self.draw_rows("Day positions", body.get('day') or [])


def main():
    """Lay out the page and handle the rerun that follows a successful connect."""
    st.set_page_config(page_title="UBI REST API test run", page_icon="🧪", layout="wide")

    defaults = {
        'base_url': f"http://{api_configuration['host']}:{api_configuration['port']}",
        'api_key': '', 'api_secret': '', 'access_token': '', 'expires_at': None,
        'token_mode': 'Current token', 'log': [], 'last_result': None, 'pending_token': None,
        'search_result': None, 'search_exchange': 'nse', 'search_segment': 'nse_equities',
        'search_q': '', 'search_limit': 20, 'instrument_id': '', 'identity_query': '', 'details_date': '',
        'master_exchange': 'mcx', 'master_segment': 'mcx_commodity_futures', 'master_date': '', 'master_rows': 100,
        'prices_interval': 'day', 'prices_from': '', 'prices_to': '', 'prices_days': '30', 'prices_adjusted': True,
        'prices_known': '', 'ticks_start': '', 'ticks_end': '', 'ticks_adjusted': True, 'ticks_rows': 500,
    }
    for name, value in defaults.items():
        st.session_state.setdefault(name, value)

    # A widget's value can only be set before the widget is drawn, so a new token from a connect is
    # parked and applied on the rerun.
    if st.session_state.pending_token is not None:
        st.session_state.access_token = st.session_state.pending_token
        st.session_state.pending_token = None

    sidebar()

    st.title("Unified Broker Interface REST API")
    top_left, top_right = st.columns([3, 1])
    top_left.caption(f"Calling `{st.session_state.base_url}`")
    if top_right.button("Ping `GET /api/`", width="stretch"):
        result = call('GET', '/api/')
        with top_left:
            show_result(result)

    tabs = st.tabs(["Session"] + [label for label, _, _ in DETAIL_ENDPOINTS] + ["Orders", "Portfolio", "Instruments"])
    with tabs[0]:
        session_tab()
    for tab, (_, path, description) in zip(tabs[1:], DETAIL_ENDPOINTS):
        with tab:
            details_tab(path, description)
    with tabs[-3]:
        st.caption("These calls only read the order book. Placing, modifying and cancelling orders are not on this page.")
        OrderDetailsView().draw()
        st.divider()
        TradesView().draw()
    with tabs[-2]:
        FundsView().draw()
        st.divider()
        HoldingsView().draw()
        st.divider()
        PositionsView().draw()
    with tabs[-1]:
        instruments_tab()

    st.divider()
    log_left, log_right = st.columns([3, 1])
    log_left.subheader("Request log")
    if log_right.button("Clear log", width="stretch"):
        st.session_state.log = []
        st.rerun()
    if st.session_state.log:
        st.dataframe(pd.DataFrame(st.session_state.log), width="stretch", hide_index=True)
    else:
        st.caption("No requests yet.")

if __name__ == "__main__":
    main()
