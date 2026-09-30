"""Runs a Stoxkart broadcast quote stream through its requests and one frame of packets, and prints the tick.

`StoxkartQuoteStream` reads a synchronous websocket-client connection in a loop of its own rather than subclassing `BrokerWebsocket`. On connecting to `wss://broadcasting-v2.stoxkart.com/` it sends an 83-byte connection header (code 10), then for each instrument a 129-byte trade subscription (code 12) and depth subscription (code 23). Each binary frame is a run of packets for one or more instruments, decoded by `StoxkartPacketDecoder`, and one tick is handed on per instrument per frame. The feed takes no login.

This program subscribes `NSE:2885` and delivers one frame holding a trade, an OHLC, a top of book, a previous close and a depth packet. No real socket is opened: a stand-in `websocket` package's `create_connection` returns a scripted connection whose `recv_data` returns the frame, and which sets the stream's `stop` event once its frames have run out, so `run` returns.

Notice that the five packets make one tick, that the change is computed against the previous close, and that the trade and update times, counted from 1980 by Stoxkart, come out as ordinary epochs.

Run it from the project root:

    python examples/stock_brokers/websockets/stoxkart/StoxkartQuoteStream/example_1_streaming_one_frame.py
"""

import logging
import struct
import sys

from stock_brokers.websockets.stoxkart import (
    StoxkartQuoteStream,
)


class ReceiveTimeout(Exception):
    """A stand-in for `websocket.WebSocketTimeoutException`: nothing arrived within the receive timeout."""


class FrameOpcodes:
    """The websocket frame opcodes the Stoxkart streams compare against, as `websocket.ABNF` holds them.

    Attributes:
        OPCODE_TEXT (int): A text frame.
        OPCODE_BINARY (int): A binary frame.
        OPCODE_CLOSE (int): A close frame.
    """

    OPCODE_TEXT = 1
    OPCODE_BINARY = 2
    OPCODE_CLOSE = 8


class ScriptedSynchronousConnection:
    """A stand-in for a synchronous `websocket.WebSocket` that returns scripted frames from `recv_data`.

    Attributes:
        frames (list): Pairs of an opcode and the frame's bytes, in the order they arrive.
        when_empty (callable | None): Called once the last frame has been read, to stop the stream.
    """

    def __init__(self, frames, when_empty):
        """Keeps the frames.

        Args:
            frames (list): Pairs of an opcode and the frame's bytes, in the order they arrive.
            when_empty (callable | None): Called once the last frame has been read, to stop the stream.

        Returns:
            None: This method returns nothing.
        """
        self.frames = frames
        self.when_empty = when_empty

    def send_binary(self, data):
        """Prints a binary request the stream sends.

        Args:
            data (bytes): The request.

        Returns:
            None: This method returns nothing.
        """
        print(f'Sent binary request with code {data[0]} and {len(data)} bytes')

    def send(self, data):
        """Prints a text message the stream sends.

        Args:
            data (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'Sent: {data}')

    def recv_data(self):
        """Returns the next scripted frame, or times out once they have run out.

        Returns:
            tuple: The opcode and the frame's bytes.

        Raises:
            ReceiveTimeout: When no scripted frame is left.
        """
        if not self.frames:
            raise ReceiveTimeout()
        frame = self.frames.pop(0)
        if not self.frames and self.when_empty is not None:
            self.when_empty()
        return frame

    def close(self):
        """Accepts the stream's request to close.

        Returns:
            None: This method returns nothing.
        """


class ScriptedSynchronousModule:
    """A stand-in for the `websocket` package that hands out scripted synchronous connections in turn.

    Attributes:
        plans (list): Each connection's frames, in the order the stream connects.
        when_finished (callable | None): Called after the last connection's last frame, to stop the stream.
        ABNF (FrameOpcodes): The frame opcodes.
        WebSocketTimeoutException (type): The error `recv_data` raises when nothing arrived.
    """

    def __init__(self, plans):
        """Keeps the plans.

        Args:
            plans (list): Each connection's frames, in the order the stream connects.

        Returns:
            None: This method returns nothing.
        """
        self.plans = plans
        self.when_finished = None
        self.ABNF = FrameOpcodes()
        self.WebSocketTimeoutException = ReceiveTimeout

    def create_connection(self, url, timeout):
        """Opens the next scripted connection.

        Args:
            url (str): The socket URL.
            timeout (int): The receive timeout in seconds.

        Returns:
            ScriptedSynchronousConnection: The connection.
        """
        print(f'Connecting to {url}')
        frames = self.plans.pop(0)
        when_empty = None
        if not self.plans:
            when_empty = self.when_finished
        return ScriptedSynchronousConnection(frames, when_empty)


class BroadcastPackets:
    """Builds Stoxkart broadcast packets, little endian, as `wss://broadcasting-v2.stoxkart.com/` sends them."""

    def packet(self, segment, scrip, code, body):
        """One packet: the 11-byte header, then its body.

        Args:
            segment (int): The broadcast segment, 1 for NSE.
            scrip (int): The instrument's token.
            code (int): The packet code.
            body (bytes): The packet's fields.

        Returns:
            bytes: The packet.
        """
        return struct.pack('<BIIBB', segment, scrip, 0, 11 + len(body), code) + body

    def trade(self, segment, scrip, last_price, volume):
        """A trade packet (code 1), with the times counted from 1980 as Stoxkart counts them.

        Args:
            segment (int): The broadcast segment.
            scrip (int): The instrument's token.
            last_price (float): The last price in rupees.
            volume (int): The day's volume.

        Returns:
            bytes: The packet.
        """
        last_trade = 1790311528 - 315532800
        last_update = 1790311529 - 315532800 + 19800
        body = struct.pack('<fHIfiii', last_price, 25, volume, last_price - 1.5, 0, last_trade, last_update)
        return self.packet(segment, scrip, 1, body)

    def ohlc(self, segment, scrip, day_open, high, low):
        """An OHLC packet (code 3), whose close field is not used.

        Args:
            segment (int): The broadcast segment.
            scrip (int): The instrument's token.
            day_open (float): The day's open.
            high (float): The day's high.
            low (float): The day's low.

        Returns:
            bytes: The packet.
        """
        return self.packet(segment, scrip, 3, struct.pack('<ffff', day_open, 0.0, high, low))

    def previous_close(self, segment, scrip, close):
        """A previous close packet (code 32).

        Args:
            segment (int): The broadcast segment.
            scrip (int): The instrument's token.
            close (float): The previous session's close.

        Returns:
            bytes: The packet.
        """
        return self.packet(segment, scrip, 32, struct.pack('<f', close))

    def top_of_book(self, segment, scrip, total_offered, total_bid):
        """A top of book packet (code 6).

        Args:
            segment (int): The broadcast segment.
            scrip (int): The instrument's token.
            total_offered (int): The total quantity offered.
            total_bid (int): The total quantity bid.

        Returns:
            bytes: The packet.
        """
        return self.packet(segment, scrip, 6, struct.pack('<II', total_offered, total_bid))

    def depth(self, segment, scrip, best_bid):
        """A depth packet (code 2) with five levels a side.

        Args:
            segment (int): The broadcast segment.
            scrip (int): The instrument's token.
            best_bid (float): The best bid; the best offer is 0.5 above it.

        Returns:
            bytes: The packet.
        """
        body = b''
        for level in range(5):
            body = body + struct.pack('<IIHHff', 100 + level, 200 + level, 3 + level, 4 + level, best_bid - level * 0.25, best_bid + 0.5 + level * 0.25)
        return self.packet(segment, scrip, 2, body)


class StreamingOneFrameExample:
    """Runs a Stoxkart quote stream against one scripted frame.

    Attributes:
        stream (StoxkartQuoteStream): The stream being shown.
    """

    def __init__(self):
        """Builds the frame, the stand-in package and the stream.

        Returns:
            None: This method returns nothing.
        """
        logging.basicConfig(stream=sys.stdout, format='%(levelname)s %(message)s', level=logging.INFO)
        packets = BroadcastPackets()
        frame = packets.trade(1, 2885, 2950.5, 1204500)
        frame = frame + packets.ohlc(1, 2885, 2930.0, 2960.0, 2925.0)
        frame = frame + packets.top_of_book(1, 2885, 61000, 54000)
        frame = frame + packets.previous_close(1, 2885, 2910.0)
        frame = frame + packets.depth(1, 2885, 2950.0)
        plans = [
            [
                (
                    2,
                    frame,
                ),
            ],
        ]
        websocket_module = ScriptedSynchronousModule(plans)
        sys.modules['websocket'] = websocket_module
        instruments = [
            'NSE:2885',
        ]
        names = {
            'NSE:2885': 'NSE:RELIANCE',
        }
        self.stream = StoxkartQuoteStream(instruments, names, self.print_ticks, logging.getLogger('stoxkart.quotes'))
        websocket_module.when_finished = self.stream.stop.set

    def print_ticks(self, ticks):
        """Prints the main fields of each tick the stream handed on.

        Args:
            ticks (list): The changed ticks from one frame.

        Returns:
            None: This method returns nothing.
        """
        for tick in ticks:
            print(f"Tick {tick['id']} ({tick['instrument_token']}): last_price={tick['last_price']} volume={tick['volume']} change={tick['change']}")
            print(f"  ohlc={tick['ohlc']} buy_quantity={tick['buy_quantity']} sell_quantity={tick['sell_quantity']}")
            print(f"  last_trade_time={tick['last_trade_time']} exchange_timestamp={tick['exchange_timestamp']}")
            if tick['depth']['buy']:
                print(f"  best bid={tick['depth']['buy'][0]} best offer={tick['depth']['sell'][0]}")

    def run(self):
        """Runs the stream until the scripted connection has delivered everything.

        Returns:
            None: This method returns nothing.
        """
        exit_code = self.stream.run()
        print(f'run returned {exit_code}')


if __name__ == '__main__':
    StreamingOneFrameExample().run()
