"""Turns one NSE market picture with five-level depth into a normalized tick.

`KotakFeedDecoder` reads the binary frames of Kotak's SFeed `native_batch` feed. A frame holds packets laid end to end in little-endian byte order, and `packets` splits it at each packet's two-byte length. A packet starts with a nine-byte header (length, message code, exchange id, level, auction flag, sequence number and bitmask length). A market picture, at level 2, 4, 8 or 16, then carries a fixed body of 135 bytes with the token, quantities, times, prices and the number of depth rows a side, followed by 16-byte depth rows of quantity, price and orders, buy rows first. `tick` turns a market picture into the normalized tick, dividing each price by the exchange's divider, which is 100 for `nse_cm`.

This program builds one frame by hand with `struct`, holding a level-8 market picture for RELIANCE (`nse_cm|2885`, exchange id 1) with five rows a side, as `subscribeDepth` sends it. Prices are in paise. The decoder is given a names table that already knows the trading symbol. The tick's `received_at` comes from `time.time`, so the program fixes the clock at 10:30 IST on 2026-10-28 to print the same output on every run. It needs no other stand-ins.

Notice that every price is in rupees after the division by 100, that quantities are left as they arrived, that `change` is worked out against the previous close, and that the depth has five levels a side, best first, so the tick is in `full` mode.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakFeedDecoder/example_1_market_picture_with_depth.py
"""

import datetime
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
NSE_CM = 1


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

    def market_picture(self, exchange_id, token, prices, quantities, times, buy_rows, sell_rows):
        """A level-8 market picture with its depth rows.

        Args:
            exchange_id (int): Kotak's numeric exchange id.
            token (int): The instrument's token.
            prices (dict): `open`, `high`, `low`, `close`, `last` and `average` in the exchange's integer units.
            quantities (dict): `buy`, `sell`, `volume`, `last` and `open_interest`.
            times (dict): `last_trade` and `exchange`, in Unix seconds.
            buy_rows (list): Buy rows as (quantity, price, orders), best first.
            sell_rows (list): Sell rows as (quantity, price, orders), best first.

        Returns:
            bytes: The packet.
        """
        body = MARKET_PICTURE.pack(
            token,
            quantities['buy'],
            quantities['sell'],
            quantities['volume'],
            times['last_trade'],
            times['exchange'],
            prices['open'],
            prices['close'],
            prices['high'],
            prices['low'],
            prices['last'],
            quantities['last'],
            prices['average'],
            0,
            len(buy_rows),
            len(sell_rows),
            0,
            0,
            quantities['open_interest'],
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
        for quantity, price, orders in buy_rows + sell_rows:
            body = body + DEPTH_ROW.pack(quantity, price, orders)
        return self.packet(MARKET_PICTURE_CODE, exchange_id, 8, body)


class MarketPictureWithDepthExample:
    """Decodes one scripted SFeed frame into a tick and prints it.

    Attributes:
        decoder (KotakFeedDecoder): The decoder being shown.
        names (dict): `EXCHANGE|TOKEN` to trading symbol.
        frame (bytes): The binary frame, as Kotak would send it.
        received_at (float): The fixed clock reading, in Unix seconds.
    """

    def __init__(self):
        """Builds the decoder, the names table, the frame and the fixed clock reading.

        Returns:
            None: This method returns nothing.
        """
        self.decoder = KotakFeedDecoder()
        self.names = {
            'nse_cm|2885': 'RELIANCE-EQ',
        }
        received = datetime.datetime(2026, 10, 28, 10, 30, tzinfo=INDIA)
        self.received_at = received.timestamp()
        buy_rows = []
        sell_rows = []
        for level in range(5):
            buy_rows.append((100 + level * 10, 119840 - level * 5, 3 + level))
            sell_rows.append((200 + level * 10, 119850 + level * 5, 4 + level))
        prices = {
            'open': 119500,
            'high': 120400,
            'low': 119210,
            'close': 119620,
            'last': 119845,
            'average': 119790,
        }
        quantities = {
            'buy': 412000,
            'sell': 389500,
            'volume': 2645310,
            'last': 25,
            'open_interest': 0,
        }
        times = {
            'last_trade': int(self.received_at) - 2,
            'exchange': int(self.received_at) - 1,
        }
        self.frame = SfeedPackets().market_picture(NSE_CM, 2885, prices, quantities, times, buy_rows, sell_rows)

    def run(self):
        """Splits the frame into packets and prints the tick its market picture carries.

        Returns:
            None: This method returns nothing.
        """
        packets = self.decoder.packets(self.frame)
        print(f'Frame of {len(self.frame)} bytes holds {len(packets)} packet(s)')
        with mock.patch('time.time', return_value=self.received_at):
            tick = self.decoder.tick(packets[0], self.names)
        for name, value in tick.items():
            if name == 'depth':
                continue
            if name == 'change':
                value = round(value, 4)
            print(f'{name}: {value}')
        for side in (
            'buy',
            'sell',
        ):
            print(f'depth {side}:')
            for level in tick['depth'][side]:
                print(f"  {level['quantity']} at {level['price']} from {level['orders']} order(s)")


if __name__ == '__main__':
    MarketPictureWithDepthExample().run()
