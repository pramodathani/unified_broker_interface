"""Streams one Kite ticker frame through a quotes socket and prints the ticks it decodes.

A `ZerodhaQuotesSocket` opens `wss://ws.kite.trade`, subscribes its batch of instrument tokens in full mode, and turns each binary frame into normalized ticks that it hands to the function it was given. This program builds a frame the way Kite does, with one 184 byte full packet for NSE RELIANCE (token 738561) and one 8 byte last price packet for NSE INFY (token 408065), and lets the socket's own reconnect loop receive it.

No real socket is opened. The socket imports the `websocket` package when it connects, so the program registers a small stand-in under that name, which plays the scripted frame to the socket's handlers and prints every message the socket sends. The session is a stand-in with the one method the socket calls, `credentials`, so no Kite login happens. When the scripted connection ends, the stand-in closes the socket, which ends `run_forever`.

Notice in the output that the socket sends two messages when the connection opens, the subscription and the switch to full mode, and that Kite's integer prices come out in rupees, divided by 100. The full packet carries open interest and five levels of depth on each side, while the last price packet fills only `last_price`.

Run it from the project root:

    python examples/stock_brokers/websockets/zerodha/ZerodhaQuotesSocket/example_1_decoding_a_full_quote.py
"""

import logging
import struct
import sys

from stock_brokers.websockets.zerodha import (
    ZerodhaQuotesSocket,
)


class StandInSession:
    """A stand-in for `ZerodhaSession` that answers with fixed credentials and never logs in."""

    def credentials(self):
        """The api key and access token the socket puts in the feed URL.

        Returns:
            tuple: The api key and the access token.
        """
        return (
            'kite-api-key',
            'kite-access-token',
        )

    def log_in_again(self, stale_token):
        """Reports a login request, which this program never expects.

        Args:
            stale_token (str | None): The access token the failing connection used.

        Returns:
            None: This method returns nothing.
        """
        print(f'Asked to log in again after {stale_token}')


class ScriptedConnection:
    """A stand-in for `websocket.WebSocketApp` that plays scripted frames to the socket's handlers.

    Attributes:
        url (str): The URL the socket asked for.
        frames (list): The frames to deliver after the connection opens.
        handlers (dict): The socket's callbacks, by name.
        when_finished (callable): Called after the last frame, to close the socket.
    """

    def __init__(self, url, frames, handlers, when_finished):
        """Keeps what the socket passed in.

        Args:
            url (str): The URL the socket asked for.
            frames (list): The frames to deliver after the connection opens.
            handlers (dict): The socket's callbacks, by name.
            when_finished (callable): Called after the last frame, to close the socket.

        Returns:
            None: This method returns nothing.
        """
        self.url = url
        self.frames = frames
        self.handlers = handlers
        self.when_finished = when_finished

    def run_forever(self, **options):
        """Opens, delivers every frame, then closes, as a real connection would.

        Args:
            **options (dict): The ping settings the socket asks for.

        Returns:
            None: This method returns nothing.
        """
        print(f'Connecting to {self.url} with {options}')
        self.handlers['on_open'](self)
        for frame in self.frames:
            self.handlers['on_message'](self, frame)
        self.handlers['on_close'](self, 1000, 'normal closure')
        self.when_finished()

    def send(self, data):
        """Prints a message the socket sends to Kite.

        Args:
            data (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'Sent: {data}')

    def close(self):
        """Accepts the socket's request to close.

        Returns:
            None: This method returns nothing.
        """


class ScriptedWebsocketModule:
    """A stand-in for the `websocket` package that hands out one scripted connection.

    Attributes:
        frames (list): The frames the connection delivers.
        when_finished (callable | None): Called when the connection has delivered everything.
    """

    def __init__(self, frames):
        """Keeps the frames to deliver.

        Args:
            frames (list): The frames the connection delivers.

        Returns:
            None: This method returns nothing.
        """
        self.frames = frames
        self.when_finished = None

    def WebSocketApp(self, url, **handlers):
        """Builds the scripted connection, with the same signature as the real class.

        Args:
            url (str): The feed URL.
            **handlers (dict): The socket's `on_open`, `on_message`, `on_error` and `on_close` callbacks.

        Returns:
            ScriptedConnection: The connection.
        """
        return ScriptedConnection(url, self.frames, handlers, self.when_finished)


class KiteFrames:
    """Builds Kite ticker frames byte by byte, as `wss://ws.kite.trade` sends them."""

    def integers(self, values):
        """Packs unsigned big endian four byte integers.

        Args:
            values (list): The integers.

        Returns:
            bytes: The packed integers.
        """
        packed = b''
        for value in values:
            packed = packed + struct.pack('>I', value)
        return packed

    def full_packet(self, token):
        """A 184 byte full packet with a quote, open interest and ten depth levels.

        Args:
            token (int): The instrument token.

        Returns:
            bytes: The packet.
        """
        quote = [
            token,
            295050,
            25,
            294812,
            1204500,
            54000,
            61000,
            293000,
            296000,
            292500,
            291000,
            1790311528,
            0,
            0,
            0,
            1790311529,
        ]
        packet = self.integers(quote)
        for level in range(10):
            packet = packet + struct.pack('>IIHH', 100 + level, 295000 + level * 5, 3 + level, 0)
        return packet

    def last_price_packet(self, token, price):
        """An 8 byte last price packet.

        Args:
            token (int): The instrument token.
            price (int): The price in paise.

        Returns:
            bytes: The packet.
        """
        values = [
            token,
            price,
        ]
        return self.integers(values)

    def frame(self, packets):
        """A binary frame: the packet count, then each packet after its two byte length.

        Args:
            packets (list): The packets.

        Returns:
            bytes: The frame.
        """
        frame = struct.pack('>H', len(packets))
        for packet in packets:
            frame = frame + struct.pack('>H', len(packet)) + packet
        return frame


class DecodingAFullQuoteExample:
    """Runs a quotes socket against one scripted frame and prints the ticks.

    Attributes:
        websocket_module (ScriptedWebsocketModule): The stand-in `websocket` package.
        socket (ZerodhaQuotesSocket): The socket being shown.
    """

    def __init__(self):
        """Builds the frame, the stand-in package and the socket.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        kite_frames = KiteFrames()
        packets = [
            kite_frames.full_packet(738561),
            kite_frames.last_price_packet(408065, 150025),
        ]
        frames = [
            kite_frames.frame(packets),
        ]
        self.websocket_module = ScriptedWebsocketModule(frames)
        sys.modules['websocket'] = self.websocket_module
        tokens = [
            738561,
            408065,
        ]
        names = {
            '738561': 'NSE:RELIANCE',
            '408065': 'NSE:INFY',
        }
        self.socket = ZerodhaQuotesSocket(
            'socket_0',
            tokens,
            names,
            StandInSession(),
            self.print_ticks,
            logging.getLogger('zerodha.quotes'),
        )
        self.websocket_module.when_finished = self.socket.close

    def print_ticks(self, ticks):
        """Prints the main fields of each tick the socket decoded.

        Args:
            ticks (list): The normalized ticks from one frame.

        Returns:
            None: This method returns nothing.
        """
        for tick in ticks:
            print(f"Tick {tick['id']} on {tick['exchange']} in {tick['mode']} mode")
            change = tick['change']
            if change is not None:
                change = round(change, 4)
            print(f"  last_price={tick['last_price']} volume={tick['volume']} change={change}")
            print(f"  ohlc={tick['ohlc']}")
            print(f"  oi={tick['oi']} last_trade_time={tick['last_trade_time']}")
            if tick['depth']['buy']:
                print(f"  best bid={tick['depth']['buy'][0]} best offer={tick['depth']['sell'][0]}")

    def run(self):
        """Runs the socket's reconnect loop until the scripted connection ends.

        Returns:
            None: This method returns nothing.
        """
        self.socket.run_forever()
        print(f'Gave up: {self.socket.gave_up}')


if __name__ == '__main__':
    DecodingAFullQuoteExample().run()
