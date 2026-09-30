"""Checks certificate fingerprints, recognises refused tokens, and runs one heartbeat with `WisdomCapitalTransport`.

Once an XTS websocket opens, the sockets compare `peer_fingerprint`, the SHA-256 of the certificate the peer presented, with the pin; a connection whose certificate cannot be read counts as matching, since the HTTPS requests are pinned already. `is_authentication_refusal` recognises XTS's refused token answers by `e-session`, `e-token` or `Invalid Token`. `handshake` returns None for a refused handshake together with the status and body. `start_heartbeat` runs a thread that sends the Engine.IO ping `2` on an interval until the connection's `closed` event is set.

This program uses a stand-in connection presenting made-up certificate bytes and one presenting nothing, a stand-in `urllib3` package that refuses a handshake, and a heartbeat with a 0.05 second interval whose stand-in connection closes itself after the first ping. No network is used.

Notice that the made-up certificate does not match the pin, that `Instrument Already Subscribed` counts as a refusal to this check, which is why the quotes socket looks for it first, and that exactly one ping is sent.

Run it from the project root:

    python examples/stock_brokers/websockets/wisdom_capital/WisdomCapitalTransport/example_2_pins_refusals_and_heartbeat.py
"""

import json
import sys
import threading

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


class PeerCertificate:
    """A stand-in for the TLS socket inside a websocket, presenting fixed certificate bytes."""

    def getpeercert(self, binary_form=False):
        """The peer's certificate.

        Args:
            binary_form (bool): Whether to return the DER bytes.

        Returns:
            bytes: Made-up certificate bytes.
        """
        return b'not the pinned certificate'


class CertificateHolder:
    """A stand-in for the websocket-client socket object that holds the TLS socket.

    Attributes:
        sock (PeerCertificate): The TLS socket.
    """

    def __init__(self):
        """Holds the stand-in TLS socket.

        Returns:
            None: This method returns nothing.
        """
        self.sock = PeerCertificate()


class ConnectionWithCertificate:
    """A stand-in for an open websocket whose peer presented a certificate.

    Attributes:
        sock (CertificateHolder): The socket object.
    """

    def __init__(self):
        """Holds the stand-in socket object.

        Returns:
            None: This method returns nothing.
        """
        self.sock = CertificateHolder()


class ConnectionWithoutCertificate:
    """A stand-in for an open websocket whose certificate cannot be read."""


class PingedConnection:
    """A stand-in for an open websocket that records pings and closes after the first.

    Attributes:
        closed (threading.Event): The connection's closed event, set after the first ping.
        sent (list): The messages sent.
    """

    def __init__(self):
        """Starts open with nothing sent.

        Returns:
            None: This method returns nothing.
        """
        self.closed = threading.Event()
        self.sent = []

    def send(self, data):
        """Records a ping and closes the connection.

        Args:
            data (str): The message.

        Returns:
            None: This method returns nothing.
        """
        self.sent.append(data)
        self.closed.set()


class PinsRefusalsAndHeartbeatExample:
    """Checks fingerprints, refusals and one heartbeat.

    Attributes:
        transport (WisdomCapitalTransport): The transport being shown.
    """

    def __init__(self):
        """Registers the stand-in urllib3 package and builds the transport.

        Returns:
            None: This method returns nothing.
        """
        refused = {
            'type': 'error',
            'code': 'e-session-0001',
            'description': 'Invalid Token',
        }
        sys.modules['urllib3'] = StandInUrllib3([
            PinnedResponse(400, json.dumps(refused)),
        ])
        self.transport = WisdomCapitalTransport()

    def run(self):
        """Prints each check and the heartbeat's pings.

        Returns:
            None: This method returns nothing.
        """
        print(f'Made-up certificate: {self.transport.peer_fingerprint(ConnectionWithCertificate())[:16]}...')
        print(f'Unreadable certificate: {self.transport.peer_fingerprint(ConnectionWithoutCertificate())[:16]}...')
        answers = [
            '{"code": "e-session-0001", "description": "Invalid Token"}',
            '{"code": "e-session-0002", "description": "Instrument Already Subscribed !"}',
            '{"type": "success"}',
        ]
        for answer in answers:
            print(f'Refusal: {self.transport.is_authentication_refusal(answer)} for {answer}')
        handshake, status, body = self.transport.handshake('/interactive', 'token=stale&userID=WC0001&apiType=INTERACTIVE')
        print(f'Refused handshake: {handshake}, {status}, {body}')
        connection = PingedConnection()
        stop = threading.Event()
        self.transport.start_heartbeat(connection, connection.closed, 0.05, stop, 'example_heartbeat')
        connection.closed.wait(5)
        print(f'Heartbeat sent: {connection.sent}')


if __name__ == '__main__':
    PinsRefusalsAndHeartbeatExample().run()
