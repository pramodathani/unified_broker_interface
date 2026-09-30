"""Shows which Stoxkart packets the decoder skips: unread codes, unsubscribed instruments and a malformed header.

`StoxkartPacketDecoder` reads only the packets the stream uses. A circuit limit packet (code 33), a 52-week range (36) or any other code is skipped, a packet for an instrument that was not subscribed is skipped, and a packet whose header declares a length shorter than the header itself ends the frame, because nothing after it can be trusted. `decode` returns only the states a packet actually changed.

This program decodes three frames: one with a circuit limit packet and a trade for an unsubscribed token, one with a trade for each of two subscribed instruments, and one whose first packet declares a length of 5. It needs no stand-ins.

Notice that the first and third frames change no state, and that the second returns both instruments in the order their packets came.

Run it from the project root:

    python examples/stock_brokers/websockets/stoxkart/StoxkartPacketDecoder/example_2_skipped_packets.py
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


class SkippedPacketsExample:
    """Decodes frames with packets the decoder skips.

    Attributes:
        decoder (StoxkartPacketDecoder): The decoder being shown.
    """

    def __init__(self):
        """Builds two subscribed states and the decoder.

        Returns:
            None: This method returns nothing.
        """
        states = {
            (1, 2885): StoxkartInstrumentState('NSE:2885', 'NSE:RELIANCE'),
            (1, 1594): StoxkartInstrumentState('NSE:1594', 'NSE:INFY'),
        }
        self.decoder = StoxkartPacketDecoder(states)

    def run(self):
        """Decodes the three frames and prints which states each changed.

        Returns:
            None: This method returns nothing.
        """
        packets = BroadcastPackets()
        circuit_limits = packets.packet(1, 2885, 33, struct.pack('<ff', 2619.0, 3201.0))
        unsubscribed = packets.trade(1, 11536, 4120.0, 5000)
        subscribed = packets.trade(1, 1594, 1500.25, 88000) + packets.trade(1, 2885, 2950.5, 1204500)
        malformed = struct.pack('<BIIBB', 1, 2885, 0, 5, 1) + packets.trade(1, 2885, 2951.0, 1204600)
        frames = [
            (
                'circuit limits and an unsubscribed trade',
                circuit_limits + unsubscribed,
            ),
            (
                'two subscribed trades',
                subscribed,
            ),
            (
                'a malformed header first',
                malformed,
            ),
        ]
        for description, frame in frames:
            touched = self.decoder.decode(frame)
            instruments = []
            for state in touched:
                instruments.append(state.instrument)
            print(f'{description}: {instruments}')


if __name__ == '__main__':
    SkippedPacketsExample().run()
