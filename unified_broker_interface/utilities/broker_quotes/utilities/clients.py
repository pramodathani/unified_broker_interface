"""
Broker API clients for a web worker, and what a worker does when a broker refuses their session.

A broker's API class is normally built by calling it, and its constructor probes an authenticated
endpoint and, when the probe fails for any reason, logs in on the spot - for Zerodha by driving a
headless Chrome. A web request must never set that off: a transient probe failure would start a
Selenium login inside the worker, and a second Kite login invalidates the token every other process holds.

So a client here is built without its constructor's probe: the object is allocated and only
`BrokerAPI.__init__` runs, which reads the broker's settings and login. Every request still goes through
`_current_login()`, so a token another process has just minted is used at once.

**The API never logs a broker in.** Logins belong to each broker's `<broker>-login.service`, the unit
`bin/<broker>/session/connect` runs under - on its morning timer, and whenever anything asks for it. When a request is
refused because the session is dead, the rule is to log in first and only then carry on, never to keep
sending the dead token. `relogin` keeps that rule without a login of its own:

- when the stored session has changed since the refused request was sent, another process has already logged
  in, and the request is sent once more with that session;
- otherwise it starts `<broker>-login.service` without waiting for it and raises `SessionUnavailable`, so this
  broker fails this request - the quote falls through to the next broker - and the requests after the login use
  its session.

systemd runs one instance of a unit at a time, so any number of refused requests, in any number of workers, start
at most one login, and `bin/<broker>/session/connect` probes the stored session before logging in, so a login asked for
after another process already refreshed the session changes nothing. A worker asks at most once every five
minutes per broker, which keeps a broker that stays refused from running the unit into its start limit.
"""

import importlib
import subprocess
import threading
import time

from stock_brokers.api.base import BrokerAPI
from utilities.configurations import get_logger

logger = get_logger("rest_api.broker_clients")

# Each broker's API class, imported lazily: several of these modules import Selenium at module level.
API_CLASSES = {
    "zerodha": ("stock_brokers.api.zerodha", "ZerodhaAPI"),
    "dhan": ("stock_brokers.api.dhan", "DhanAPI"),
    "flattrade": ("stock_brokers.api.flattrade", "FlattradeAPI"),
    "shoonya": ("stock_brokers.api.shoonya", "ShoonyaAPI"),
    "fyers": ("stock_brokers.api.fyers", "FyersAPI"),
    "groww": ("stock_brokers.api.groww", "GrowwAPI"),
    "kotak": ("stock_brokers.api.kotak", "KotakAPI"),
    "indmoney": ("stock_brokers.api.indmoney", "INDMoneyAPI"),
    "wisdom_capital": ("stock_brokers.api.wisdom_capital", "WisdomCapitalAPI"),
    "stoxkart": ("stock_brokers.api.stoxkart", "StoxkartAPI"),
}

LOGIN_UNITS = {broker: f"{broker}-login.service" for broker in
               ("zerodha", "dhan", "flattrade", "shoonya", "fyers", "groww", "kotak", "indmoney", "wisdom_capital",
                "stoxkart")}

# How long a worker waits before asking for the same broker's login again.
LOGIN_REQUEST_FLOOR_SECONDS = 300

_clients = {}
_lock = threading.Lock()
_login_requested_at = {}

class SessionUnavailable(Exception):
    """A broker refused the session and no newer one is stored yet; its login has been asked for."""

def client_for(broker):
    """
    This worker's API client for a broker, built on first use without the constructor's probe.

    - `broker` is the broker name.
    """
    with _lock:
        client = _clients.get(broker)
        if client is None:
            if broker not in API_CLASSES:
                raise ValueError(f"No API class known for broker {broker}. Known: {', '.join(sorted(API_CLASSES))}")
            module_name, class_name = API_CLASSES[broker]
            api_class = getattr(importlib.import_module(module_name), class_name)
            client = api_class.__new__(api_class)
            BrokerAPI.__init__(client, broker_name=broker)
            _clients[broker] = client
        return client

def session_marker(client):
    """
    What identifies the session a client's next request is sent with: its token and when it was issued.

    Read just before a request, and handed to `relogin` when that request is refused.

    - `client` is the broker API client.
    """
    try:
        login = client._current_login() or {}
    except Exception:
        return None
    return (login.get("access_token"), login.get("last_login"))

def request_login(broker):
    """
    Start the broker's login unit without waiting for it, at most once every five minutes from this worker.

    - `broker` is the broker name.
    """
    unit = LOGIN_UNITS.get(broker)
    if unit is None:
        logger.warning(f"{broker} has no login unit; its session is not renewed from here")
        return
    with _lock:
        now = time.monotonic()
        if now - _login_requested_at.get(broker, float("-inf")) < LOGIN_REQUEST_FLOOR_SECONDS:
            return
        _login_requested_at[broker] = now
    try:
        subprocess.run(["systemctl", "--user", "start", "--no-block", unit], check=True, capture_output=True,
                       text=True, timeout=10)
        logger.warning(f"{broker} refused the session; started {unit}")
    except Exception as exception:
        detail = getattr(exception, "stderr", None) or exception
        logger.error(f"{broker} refused the session, and {unit} could not be started: {detail}")

def relogin(broker, client, refused):
    """
    Decide what follows a request a broker refused for a dead session: return to send it once more with a newer
    stored session, or raise `SessionUnavailable` having asked for the broker's login.

    - `broker` is the broker name.
    - `client` is the broker API client the request was sent through.
    - `refused` is the `session_marker` read just before the refused request.
    """
    current = session_marker(client)
    if current is not None and current[0] and current != refused:
        logger.info(f"{broker} refused a session another process has since replaced; sending with the new one")
        return
    request_login(broker)
    raise SessionUnavailable(f"{broker} refused the session; its login has been started, so try again shortly")
