"""Learns each exchange's price divider from Kotak's authentication answer, then decodes a batch with a touch line, a skipped packet and a truncated tail.

Kotak answers the SFeed authentication message with message code 1119, and again with 1117, carrying every exchange's numeric id and price divider. `KotakFeedDecoder.learn_exchanges` takes them from that answer's `exchanges`. Most exchanges divide by 100, but currency derivatives on `cde_fo` and `bse_cd` divide by 10,000,000, so a decoder that has not learned the dividers would read a rupee-dollar rate of 88.2 as 8,820,000.

A frame can hold several packets. `packets` keeps only whole ones, and stops at a length that runs past the end of the frame. `tick` returns None for any packet that is not a market picture at level 2, 4, 8 or 16. A level-4 packet is a touch line: whatever depth counts its body declares, it is read as one row a side.

This program builds the frames by hand with `struct`. It decodes a USDINR future on `cde_fo` (exchange id 3) once with a fresh decoder and once after learning the dividers. It then decodes one batch frame holding four things: a level-8 picture of the USDINR future, a level-4 touch line for a CRUDEOIL future on `mcx_fo` (exchange id 9) whose body declares five rows a side but carries one, a closing auction packet (message code 104, level 0), and the first 30 bytes of a further picture, cut short. The tick's `received_at` comes from `time.time`, so the clock is fixed at 15:00 IST on 2026-10-28. It needs no other stand-ins.

Notice the currency price before and after learning, that the batch yields three whole packets and two ticks with the 30 cut-short bytes left unread, that the closing auction packet gives no tick, and that the touch line has one level a side although its body declares five.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakFeedDecoder/example_2_dividers_touch_line_and_skipped_packets.py
"""

import datetime
import json
import struct
import zoneinfo
from unittest import mock

from stock_brokers.websockets.kotak import (
    KotakFeedDecoder,
)

INDIA = zoneinfo.ZoneInfo('Asia/Kolkata')
PACKET_HEADER = struct.Struct('<HHbBBBB')
MARKET_PICTURE = struct.Struct('<IqqqqqIIIIIqIIIIhiIdiIIIIIBI')
DEPTH_ROW = struct.Struct('<qii')
MARKET_PICTURE_CODE = 7208
CLOSING_AUCTION_CODE = 104
CDE_FO = 3
MCX_FO = 9


class SfeedPackets:
    """Builds the little-endian packets of Kotak's SFeed `native_batch` feed."""

    def packet(self, message_code, exchange_id, level, body):
        """A packet: its nine-byte header, which starts with the packet's whole length, and its body.

        Args:
            message_code (int): The message code.
            exchange_id (int): Kotak's numeric exchange id.
            level (int): The packet's level.
            body (bytes): Everything after the header.

        Returns:
            bytes: The packet.
        """
        length = PACKET_HEADER.size + len(body)
        return PACKET_HEADER.pack(length, message_code, exchange_id, level, 0, 1, 0) + body

    def market_picture(self, exchange_id, token, last_price, close, level, declared_rows, rows, open_interest):
        """A market picture whose other prices sit a little around the last price.

        Args:
            exchange_id (int): Kotak's numeric exchange id.
            token (int): The instrument's token.
            last_price (int): The last price in the exchange's integer units.
            close (int): The previous close in the exchange's integer units.
            level (int): The packet's level.
            declared_rows (int): How many depth rows a side the body declares.
            rows (list): The depth rows the packet carries, as (quantity, price, orders), buy rows first.
            open_interest (int): The open interest.

        Returns:
            bytes: The packet.
        """
        step = max(last_price // 1000, 1)
        body = MARKET_PICTURE.pack(
            token,
            4100,
            3900,
            18250,
            1793178000,
            1793178001,
            close,
            close,
            last_price + step,
            close - step,
            last_price,
            2,
            last_price,
            0,
            declared_rows,
            declared_rows,
            0,
            0,
            open_interest,
            0.0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )
        for quantity, price, orders in rows:
            body = body + DEPTH_ROW.pack(quantity, price, orders)
        return self.packet(MARKET_PICTURE_CODE, exchange_id, level, body)


class DividersTouchLineAndSkippedPacketsExample:
    """Decodes scripted SFeed frames before and after learning the exchanges' dividers.

    Attributes:
        decoder (KotakFeedDecoder): The decoder being shown.
        names (dict): `EXCHANGE|TOKEN` to trading symbol.
        authentication_answer (str): Kotak's answer to the authentication message.
        currency_picture (bytes): A level-8 USDINR picture on `cde_fo`.
        batch (bytes): A frame holding four packets, the last one cut short.
        received_at (float): The fixed clock reading, in Unix seconds.
    """

    def __init__(self):
        """Builds the decoder, the authentication answer and the frames.

        Returns:
            None: This method returns nothing.
        """
        self.decoder = KotakFeedDecoder()
        self.names = {
            'cde_fo|10465': 'USDINR26NOVFUT',
            'mcx_fo|440001': 'CRUDEOIL26NOVFUT',
        }
        received = datetime.datetime(2026, 10, 28, 15, 0, tzinfo=INDIA)
        self.received_at = received.timestamp()
        self.authentication_answer = json.dumps({
            'message_code': 1119,
            'format': 'native_batch',
            'exchanges': {
                'nse_cm': {
                    'value': 1,
                    'divider': 100,
                },
                'cde_fo': {
                    'value': CDE_FO,
                    'divider': 10000000,
                },
                'mcx_fo': {
                    'value': MCX_FO,
                    'divider': 100,
                },
            },
        })
        packets = SfeedPackets()
        currency_rows = [
            (12, 881975000, 3),
            (40, 882025000, 5),
        ]
        self.currency_picture = packets.market_picture(CDE_FO, 10465, 882000000, 881225000, 8, 1, currency_rows, 245000)
        touch_line_rows = [
            (3, 951750, 2),
            (4, 951850, 1),
        ]
        touch_line = packets.market_picture(MCX_FO, 440001, 951800, 949800, 4, 5, touch_line_rows, 13801)
        auction = packets.packet(CLOSING_AUCTION_CODE, 1, 0, struct.pack('<IIqq', 2885, 0, 0, 0))
        cut_short = packets.market_picture(MCX_FO, 440001, 951900, 949800, 8, 0, [], 13801)[:30]
        self.batch = self.currency_picture + touch_line + auction + cut_short

    def print_tick(self, tick):
        """Prints the main fields of one tick, or that the packet gave none.

        Args:
            tick (dict | None): The tick, or None.

        Returns:
            None: This method returns nothing.
        """
        if tick is None:
            print('  no tick')
            return
        print(f"  {tick['id']} ({tick['instrument_token']}) in {tick['mode']} mode: last_price={tick['last_price']} close={tick['ohlc']['close']} oi={tick['oi']}")
        print(f"    buy {tick['depth']['buy']}")
        print(f"    sell {tick['depth']['sell']}")

    def run(self):
        """Decodes the currency picture before and after learning, and then the batch packet by packet.

        Returns:
            None: This method returns nothing.
        """
        with mock.patch('time.time', return_value=self.received_at):
            print('USDINR before learning the dividers:')
            self.print_tick(self.decoder.tick(self.currency_picture, self.names))
            answer = json.loads(self.authentication_answer)
            print(f"Learning exchanges from message code {answer['message_code']}: {sorted(answer['exchanges'])}")
            self.decoder.learn_exchanges(answer['exchanges'])
            print('USDINR after learning the dividers:')
            self.print_tick(self.decoder.tick(self.currency_picture, self.names))
            packets = self.decoder.packets(self.batch)
            whole_bytes = 0
            for packet in packets:
                whole_bytes = whole_bytes + len(packet)
            print(f'Batch of {len(self.batch)} bytes holds {len(packets)} whole packet(s), leaving {len(self.batch) - whole_bytes} bytes of a cut-short packet unread')
            for packet in packets:
                length, message_code, exchange_id, level, _, _, _ = PACKET_HEADER.unpack_from(packet, 0)
                print(f'Packet of {length} bytes, message code {message_code}, exchange {exchange_id}, level {level}:')
                self.print_tick(self.decoder.tick(packet, self.names))


if __name__ == '__main__':
    DividersTouchLineAndSkippedPacketsExample().run()
