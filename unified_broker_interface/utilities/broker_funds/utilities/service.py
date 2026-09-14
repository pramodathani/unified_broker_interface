"""
One broker's funds, read live from the broker, for the order router checking whether a broker can pay for an order.

The account's funds for `/api/portfolio/funds` come from `unified:portfolio:funds`, which `bin/unified/funds` keeps;
this is only the placement check, where a balance read from the broker just before real money moves is worth the call.

**A dead session.** When a broker refuses the session, it is asked once more only if another process has
stored a newer session since; otherwise its `<broker>-login.service` is started and the read fails, so the router
reports the broker's funds as unreadable. See `broker_quotes/utilities/clients.py`.
"""

from unified_broker_interface.utilities.broker_funds.dhan import DhanFundsSource
from unified_broker_interface.utilities.broker_funds.flattrade import FlattradeFundsSource
from unified_broker_interface.utilities.broker_funds.fyers import FyersFundsSource
from unified_broker_interface.utilities.broker_funds.groww import GrowwFundsSource
from unified_broker_interface.utilities.broker_funds.indmoney import IndmoneyFundsSource
from unified_broker_interface.utilities.broker_funds.kotak import KotakFundsSource
from unified_broker_interface.utilities.broker_funds.shoonya import ShoonyaFundsSource
from unified_broker_interface.utilities.broker_funds.stoxkart import StoxkartFundsSource
from unified_broker_interface.utilities.broker_funds.wisdom_capital import WisdomCapitalFundsSource
from unified_broker_interface.utilities.broker_funds.zerodha import ZerodhaFundsSource
from unified_broker_interface.utilities.broker_quotes.utilities.clients import client_for, relogin, session_marker

# Brokers whose funds module is in service.
SOURCES = {source.BROKER_NAME: source() for source in (ZerodhaFundsSource, DhanFundsSource, FlattradeFundsSource,
                                                        FyersFundsSource, GrowwFundsSource, IndmoneyFundsSource,
                                                        KotakFundsSource, ShoonyaFundsSource, StoxkartFundsSource,
                                                        WisdomCapitalFundsSource)}

def _read(broker):
    """
    One broker's funds record, asked once more when the session was refused and another process has stored a newer one.

    - `broker` is the broker name.
    """
    source = SOURCES[broker]
    client = client_for(broker)
    session = session_marker(client)
    try:
        data = source.fetch(client)
    except Exception as exception:
        if not source.is_authentication_error(exception):
            raise
        relogin(broker, client, session)
        data = source.fetch(client)
    return source.normalize(data)

def read_funds(broker):
    """
    One broker's funds record, read live, for a caller that needs a single broker's figures - the order router
    checking whether a broker can pay for an order.

    - `broker` is the broker name.
    """
    return _read(broker)
