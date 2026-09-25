# Test page

The test page is a small Streamlit web app for trying the read-only routes of the API by hand. Every button sends one real request to the running API and shows the status, the time it took, any `X-` response headers and the body. It is meant for checking that the API and its background scripts are healthy, and for seeing what a response looks like before you write a client.

!!! note "The page never touches an order"
    The page only reads. It calls the two order book reads, but it has no way to place, modify, cancel or flatten an order, so it cannot move money.

## Starting it

The page needs the API to be running first, because every button calls it. The commands below start both, in two terminals.

```bash
bin/rest-api                 # the API, on 127.0.0.1:8080 (or: bin/rest-api --dev)
bin/rest-api-app             # the test page, on http://127.0.0.1:8501
```

`bin/rest-api-app` takes two options, listed in the table below.

| Option | Default | Effect |
|---|---|---|
| `--port` | `8501` | The port the page is served on |
| `--lan` | off | Listen on every interface (`0.0.0.0`) instead of `127.0.0.1` only, so the page can be opened from another machine |

The wrapper exists for two reasons. Streamlit is installed only inside the project's virtual environment, so a bare `streamlit run` is not found unless that environment is activated. And Streamlit's first interactive run stops to ask for an email address before it serves anything, which looks exactly like a hang, so the wrapper runs it headless with usage statistics turned off.

!!! warning "`--lan` exposes the page to your network"
    The sidebar can load the API key and secret from MongoDB, and every response shows real account data. Use `--lan` only on a network you trust.

## Layout

The page has a sidebar for the connection and the token, a row of tabs for the route groups, and a request log at the bottom. The sketch below shows how it is arranged.

```text
┌──────────────────────┬──────────────────────────────────────────────────────────────┐
│ SIDEBAR              │ Unified Broker Interface REST API          [Ping GET /api/]  │
│                      │ Calling http://127.0.0.1:8080                                │
│ Connection           ├──────────────────────────────────────────────────────────────┤
│  API base URL        │ Session │ Users │ Brokers │ Exchanges │ Orders │ Portfolio │ │
│                      │ Instruments                                                  │
│ Credentials          ├──────────────────────────────────────────────────────────────┤
│  [Load from MongoDB  │                                                              │
│   settings]          │   the selected tab's buttons, inputs and results             │
│  api-key   ******    │   HTTP 200 · 14 ms · X-Mapping-Date: 2026-09-26              │
│  api-secret ******   │   { ...response body as JSON, and as a table for lists... }  │
│                      │                                                              │
│ Access token         ├──────────────────────────────────────────────────────────────┤
│  access-token        │ Request log                                    [Clear log]   │
│  Expires at ...      │  time · method · path · headers sent · status · ms           │
│  ( ) Current token   │                                                              │
│  ( ) No token        │                                                              │
│  ( ) Wrong token     │                                                              │
└──────────────────────┴──────────────────────────────────────────────────────────────┘
```

### The sidebar

The sidebar holds everything the page needs to reach the API, as listed below.

- **API base URL** starts as `http://<host>:<port>` from `UNIFIED_BROKER_INTERFACE_API_HOST` and `UNIFIED_BROKER_INTERFACE_API_PORT`, and can be edited.
- **Load from MongoDB settings** fills the key and secret from the `unified_broker_interface` document in the MongoDB `settings` collection. You can also type them in.
- **access-token** is filled in by a successful connect, and shows when it expires. You can edit it to try an old token.
- **Send with requests** chooses what goes in the `access-token` header of every call, as the table below explains.

| Token mode | What is sent | What it is for |
|---|---|---|
| Current token | The token in the `access-token` field | Normal use |
| No token | No `access-token` header at all | Seeing `401 Access token is required` |
| Wrong token | A fresh random UUID | Seeing `401 Invalid access token` |

### The tabs

Each tab covers one group of routes. The table below lists every button and the route it calls.

| Tab | Controls | Route called |
|---|---|---|
| (top of page) | Ping `GET /api/` | `GET /api/` |
| Session | Connect | `POST /api/session/connect` |
| Session | Connect with a wrong secret | `POST /api/session/connect`, with `api-secret: wrong-secret` |
| Session | Get status | `GET /api/session/status` |
| Session | Disconnect | `DELETE /api/session/disconnect` |
| Users | Send | `GET /api/users/details` |
| Brokers | Send | `GET /api/brokers/details` |
| Exchanges | Send | `GET /api/exchanges/details` |
| Orders | Send, under Order details | `GET /api/orders/details` |
| Orders | Send, under Trades | `GET /api/orders/trades` |
| Portfolio | Send, under Funds | `GET /api/portfolio/funds` |
| Portfolio | Send, under Holdings | `GET /api/portfolio/holdings` |
| Portfolio | Send, under Positions | `GET /api/portfolio/positions` |
| Instruments | Search | `GET /api/instruments/search` |
| Instruments | Segments | `GET /api/instruments/segments` |
| Instruments | Details | `GET /api/instruments/details` |
| Instruments | Master (stream) | `GET /api/instruments/master` |
| Instruments | `/ltp`, `/ohlc`, `/quote` | `GET /api/instruments/ltp`, `ohlc`, `quote` |
| Instruments | Prices | `GET /api/instruments/prices` |
| Instruments | Ticks (stream) | `GET /api/instruments/ticks` |

!!! warning "Disconnect ends everyone's session"
    The Disconnect button revokes the one token the whole application shares, so every other client using it starts getting `401` too. A Connect after that issues a new token.

The table below lists the routes the page does not call. Use `curl` or your own client for these.

| Route | Why it is not on the page |
|---|---|
| `GET /api/instruments/additional_details` | Not wired to a button |
| `POST /api/orders/place` | Places a real order |
| `PUT /api/orders/modify` | Changes a real order |
| `DELETE /api/orders/cancel` | Cancels a real order |
| `POST /api/orders/flatten` | Cancels every open order and closes every position |

### The Instruments tab

The Instruments tab is the busiest. It starts with a search that fills in the instrument every other button on the tab acts on, so a typical session follows the steps below.

1. Choose an exchange and a segment, type a term such as `RELIANCE`, `NIFTY` or `CRUDEOIL`, and press **Search**. The limit starts at 20 and can go up to 200.
2. Pick a result from the list and press **Use this instrument**. Its id goes into the `instrument_id` field.
3. Press any of the catalogue, live quote, prices or ticks buttons. They all send that `instrument_id`.

When the `instrument_id` field is empty, the buttons send the **identity query** field instead, parsed as `name=value` pairs joined by `&`, such as `exchange=nse&segment=equities&symbol=INFY`.

The two streaming routes, `master` and `ticks`, are read only as far as the preview needs. The page decodes the JSON array object by object as it arrives and closes the connection once it has the number of rows set in **rows to preview**, so a listing of every instrument, which runs to over a hundred megabytes, does not have to be downloaded to see its first rows.

The table below lists the starting values of the tab's inputs.

| Input | Starts as |
|---|---|
| Search exchange and segment | `nse`, `nse_equities` |
| Search limit | 20 |
| Master exchange and segment | `mcx`, `mcx_commodity_futures` |
| Master rows to preview | 100 |
| Prices interval | `day` |
| Prices days | 30 |
| Prices adjusted | checked |
| Ticks adjusted | checked |
| Ticks rows to preview | 500 |

!!! note "One interval in the list is refused"
    The prices interval list offers `day`, `15minute`, `20minute`, `60minute`, `minute`, `5minute` and `30minute`. The API has no interval called `minute` (the one-minute interval is `1minute`), so choosing it returns `400 interval must be one of ...`.

### Results and the request log

Every result starts with a colored line: green for a 2xx status, amber for 4xx and red for anything else. The line gives the status, the time in milliseconds and any `X-` headers, such as `X-Mapping-Date` or `X-Price-Basis`. Below it is the body as JSON. The detail, order book, portfolio and streaming buttons also show a list body as a table, and the order book and portfolio views draw the `brokers` statuses of any answer that carries them, including a `502` or `503`, and the document's own tables when the status is `200`.

Every call is added to the top of the request log at the bottom of the page, with its time, method, path and query, the names of the headers sent, the status and the time taken. Header values are never logged, so the secret and the token do not appear in the log. **Clear log** empties it.

??? note "Under the hood"
    - Launcher: `bin/rest-api-app`, which replaces itself with `streamlit run test_runs/rest_api_app.py --server.headless true --server.address <address> --server.port <port> --browser.gatherUsageStats false`.
    - Page: `test_runs/rest_api_app.py`. Each request uses `requests` with a 60-second timeout.
    - The portfolio and order book views share one base class, `UnifiedDocumentView`, which draws the `brokers` table and each document's own tables.
