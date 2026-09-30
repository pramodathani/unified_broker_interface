"""Opens an XTS Engine.IO session through `WisdomCapitalTransport` and derives the websocket URL, heartbeat and TLS options from it.

`WisdomCapitalTransport` holds what both Wisdom Capital sockets need to reach XTS. `request` sends an HTTPS request through a urllib3 pool pinned to the platform's certificate, because the certificate is issued to the platform provider's domain rather than Wisdom Capital's. `handshake` opens an Engine.IO session over polling and decodes the answer with `first_json_object`, since the JSON is framed with a length prefix. `heartbeat_seconds` picks half the shorter of the server's ping interval and timeout, `websocket_url` attaches a websocket to the session, and `ssl_options` relaxes the hostname check because the pin is checked once the websocket opens.

This program performs one handshake and one plain request against a stand-in `urllib3` package, whose pool prints each request and gives a scripted answer, and reads a polling body with no JSON in it. No network is used.

Notice that the heartbeat is 10 seconds, half of the 20 second ping timeout, and that `check_hostname` is off while certificate verification stays required.

Run it from the project root:

    python examples/stock_brokers/websockets/wisdom_capital/WisdomCapitalTransport/example_1_engine_io_handshake.py
"""

import json
import ssl
import sys

from stock_brokers.websockets.wisdom_capital import (
    WisdomCapitalTransport,
)


class PinnedResponse:
    """A stand-in for the `urllib3` response of one XTS request.

    Attributes:
        status (int): The HTTP status.
        data (bytes): The body.
    """

    def __init__(self, status, text):
        """Keeps the answer.

        Args:
            status (int): The HTTP status.
            text (str): The body as text.

        Returns:
            None: This method returns nothing.
        """
        self.status = status
        self.data = text.encode()


class PinnedPool:
    """A stand-in for `urllib3.HTTPSConnectionPool` that answers from a shared script.

    Attributes:
        answers (list): The answers still to give, shared by every pool.
    """

    def __init__(self, answers):
        """Keeps the shared answers.

        Args:
            answers (list): The answers still to give, shared by every pool.

        Returns:
            None: This method returns nothing.
        """
        self.answers = answers

    def request(self, method, path, body=None, headers=None, timeout=None):
        """Prints the request and gives the next scripted answer.

        Args:
            method (str): The HTTP method.
            path (str): The path, with its query string.
            body (str | None): The JSON body.
            headers (dict | None): The request headers.
            timeout (int | None): The request timeout in seconds.

        Returns:
            PinnedResponse: The answer.
        """
        shown = path.split('?')[0]
        if body is not None:
            code = json.loads(body).get('xtsMessageCode')
            shown = f'{shown} for message code {code}'
        answer = self.answers.pop(0)
        print(f'HTTPS {method} {shown}: HTTP {answer.status}')
        return answer


class StandInUrllib3:
    """A stand-in for the `urllib3` package whose pools answer from one script.

    Attributes:
        answers (list): The answers, in the order requests are made.
    """

    def __init__(self, answers):
        """Keeps the answers.

        Args:
            answers (list): The answers, in the order requests are made.

        Returns:
            None: This method returns nothing.
        """
        self.answers = answers

    def HTTPSConnectionPool(self, host, port, assert_fingerprint=None):
        """Builds a pool, with the same signature as the real class.

        Args:
            host (str): The host.
            port (int): The port.
            assert_fingerprint (str | None): The certificate pin.

        Returns:
            PinnedPool: The pool.
        """
        return PinnedPool(self.answers)


class EngineIoHandshakeExample:
    """Performs a handshake and derives the connection details from it.

    Attributes:
        transport (WisdomCapitalTransport): The transport being shown.
    """

    def __init__(self):
        """Registers the stand-in urllib3 package and builds the transport.

        Returns:
            None: This method returns nothing.
        """
        handshake = {
            'sid': 'engine-session-1',
            'upgrades': [
                'websocket',
            ],
            'pingInterval': 25000,
            'pingTimeout': 20000,
        }
        text = json.dumps(handshake)
        success = {
            'type': 'success',
        }
        answers = [
            PinnedResponse(200, f'{len(text) + 1}:0{text}2:40'),
            PinnedResponse(200, json.dumps(success)),
        ]
        sys.modules['urllib3'] = StandInUrllib3(answers)
        self.transport = WisdomCapitalTransport()

    def run(self):
        """Prints the handshake and everything derived from it.

        Returns:
            None: This method returns nothing.
        """
        query = 'token=market-data-token-1&userID=WCMD01&publishFormat=JSON&broadcastMode=Full'
        handshake, status, body = self.transport.handshake('/apimarketdata', query)
        print(f'Handshake {status}: {handshake}')
        print(f'Heartbeat every {self.transport.heartbeat_seconds(handshake, 25.0)} seconds')
        print(f'Heartbeat without limits from the server: {self.transport.heartbeat_seconds({}, 25.0)} seconds')
        print(f"Websocket URL: {self.transport.websocket_url('/apimarketdata', handshake, query)}")
        context = self.transport.ssl_options()['context']
        print(f'check_hostname={context.check_hostname} verify_mode={context.verify_mode == ssl.CERT_REQUIRED}')
        subscription = {
            'xtsMessageCode': 1501,
        }
        response = self.transport.request('PUT', '/apimarketdata/instruments/subscription', token='market-data-token-1', body=subscription)
        print(f'Request answered {response.status}: {response.data.decode()}')
        print(f"First JSON object in a body without one: {self.transport.first_json_object('2:40')}")


if __name__ == '__main__':
    EngineIoHandshakeExample().run()
