"""
Which broker's ticks an instrument takes, when more than one broker streams it.

The unified table and quote cache do not blend brokers. At any moment one broker owns an
instrument and only its ticks are written; another broker's ticks for the same instrument are
dropped unless the owner goes unhealthy, when the best healthy backup takes over, and the owner
takes the instrument back once it has been healthy again for a while. The ownership engine in
`bin/unified/instruments/websocket_quotes` applies these rules, and `rank` orders brokers by them wherever one has to be
picked first.

The priority order is a starting point, not a measurement. Zerodha leads because its feed runs in
production and its decoding has been checked against live packets; the rest follow roughly by how
much of their feed has been verified. Reorder it as live sessions compare the brokers.

A broker is used only once it is in VERIFIED_BROKERS - or, until then, only as a last resort for an
instrument no verified broker streams. A broker joins the set once its normalizer's assumptions
(quantity basis, close semantics, timestamps) have been checked live.
"""

# Highest priority first. Used for every exchange and kind of instrument unless overridden below.
DEFAULT_PRIORITY = ("zerodha", "dhan", "kotak", "flattrade", "shoonya", "fyers",
                    "wisdom_capital", "groww", "indmoney", "stoxkart")

# Exchanges some brokers do not stream at all. Absent brokers are simply never candidates, so this
# only keeps the order honest to read.
EXCHANGE_PRIORITY = {
    "mcx": ("zerodha", "dhan", "kotak", "flattrade", "shoonya", "fyers", "wisdom_capital", "groww", "stoxkart"),
    "ncdex": ("shoonya", "wisdom_capital"),
}

VERIFIED_BROKERS = frozenset({"zerodha"})

# A socket with no message for this long is unhealthy, whatever its instruments are doing. It has to
# be longer than the gap between signs of life on a quiet but healthy socket: Zerodha and Noren send
# heartbeats every second or three, but Kotak, Fyers and Groww send none, and those sockets show they
# are alive only through the websocket ping answered every 30 seconds - measured on 2026-09-13 at 19
# to 27 seconds between reports. 45 seconds covers a ping and its 10 second timeout. A socket that
# actually closes is reported at once by its feed and fails over without waiting for this.
STALE_SOCKET_SECONDS = 45.0

# An owner whose socket is alive but which has not sent an instrument for this long, while a backup
# has sent it several times since, has lost that instrument's subscription.
INSTRUMENT_LAG_SECONDS = 60.0
INSTRUMENT_LAG_BACKUP_TICKS = 3

# A higher priority broker must have been continuously healthy this long before it takes an
# instrument back, so a flapping connection does not pull ownership to and fro.
HANDBACK_HEALTHY_SECONDS = 60.0

# When an instrument is first seen from a broker that is not its top choice, how long to wait for a
# better one before settling.
INITIAL_GRACE_SECONDS = 5.0

def priority_for(exchange):
    """
    The broker priority for an exchange.

    Args:
        exchange (str): Canonical exchange, for example "nse".

    Returns:
        tuple[str]: Broker names, highest priority first.
    """
    return EXCHANGE_PRIORITY.get(exchange, DEFAULT_PRIORITY)

def rank(broker, exchange, verified=VERIFIED_BROKERS):
    """
    A broker's sort key for an exchange: verified brokers before unverified, then by priority.

    Args:
        broker (str): The broker name.
        exchange (str): Canonical exchange.
        verified (frozenset): The brokers treated as verified.

    Returns:
        tuple[int, int]: Lower sorts first. A broker missing from the priority list sorts last.
    """
    order = priority_for(exchange)
    position = order.index(broker) if broker in order else len(order)
    return (0 if broker in verified else 1, position)
