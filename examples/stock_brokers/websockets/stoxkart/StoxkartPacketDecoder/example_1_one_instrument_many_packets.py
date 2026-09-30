"""Decodes one Stoxkart broadcast frame of five packets into an instrument's state.

`StoxkartPacketDecoder.decode` walks the packets of one binary frame, each starting with an 11-byte header of segment, scrip id, a second id, length and code, and applies each to the state of the instrument it names: trade (code 1), depth (2), OHLC (3), top of book (6) and previous close (32). It returns the states the frame changed, each once. Prices arrive as 32-bit floats and are rounded to four decimal places, and Stoxkart's times, counted in seconds from 1980, become epochs.

This program builds a frame with one packet of each kind for NSE token 2885 and decodes it. It needs no stand-ins.

Notice that five packets return one state, and that the trade time (UTC) and the update time (India's wall clock) come out one second apart as epochs.

Run it from the project root:

    python examples/stock_brokers/websockets/stoxkart/StoxkartPacketDecoder/example_1_one_instrument_many_packets.py
"""

import struct

from stock_brokers.websockets.stoxkart import (
    StoxkartInstrumentState,
    StoxkartPacketDecoder,
)


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


class OneInstrumentManyPacketsExample:
    """Decodes one frame into one instrument's state.

    Attributes:
        state (StoxkartInstrumentState): The instrument's state.
        decoder (StoxkartPacketDecoder): The decoder being shown.
    """

    def __init__(self):
        """Builds the state and the decoder.

        Returns:
            None: This method returns nothing.
        """
        self.state = StoxkartInstrumentState('NSE:2885', 'NSE:RELIANCE')
        states = {
            (1, 2885): self.state,
        }
        self.decoder = StoxkartPacketDecoder(states)

    def run(self):
        """Decodes the frame and prints the state's values and best levels.

        Returns:
            None: This method returns nothing.
        """
        packets = BroadcastPackets()
        frame = packets.trade(1, 2885, 2950.5, 1204500)
        frame = frame + packets.depth(1, 2885, 2950.0)
        frame = frame + packets.ohlc(1, 2885, 2930.0, 2960.0, 2925.0)
        frame = frame + packets.top_of_book(1, 2885, 61000, 54000)
        frame = frame + packets.previous_close(1, 2885, 2910.0)
        touched = self.decoder.decode(frame)
        print(f'States changed: {len(touched)}, the first being {touched[0].instrument}')
        for field, value in sorted(self.state.values.items()):
            print(f'  {field}: {value}')
        print(f"  best bid: {self.state.depth['buy'][0]}")
        print(f"  best offer: {self.state.depth['sell'][0]}")


if __name__ == '__main__':
    OneInstrumentManyPacketsExample().run()
