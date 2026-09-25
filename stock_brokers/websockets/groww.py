"""
Groww's two websockets, both NATS over a websocket at `wss://socket-api.groww.in`: the market feed and the account's order and position updates.

**The login and the socket token.**
`GrowwSession` holds the `GrowwAPI` both sockets read the REST access token from, afresh on every connect, so a login made by any process is picked up.
Before connecting, a socket generates a fresh ed25519 key pair and exchanges its public key, in NATS NKEY form, for a short-lived socket JWT and a subscription id at `POST https://api.groww.in/v1/api/apex/v1/socket/token/create/`, authorized with the access token.
HTTP 401 or 403 there means the access token is dead, which the socket treats as a refused login.
The quote sockets log in again one at a time, and only when no other socket or process has already replaced the token that failed; the order socket logs in again whenever it is refused, without that check, as it always has.

**NATS.**
The server opens with an `INFO` frame carrying a nonce; the socket answers `CONNECT` with the JWT and the nonce signed by its private key, then `PING`, then one `SUB` per subject.
NATS is line based: control lines end with CRLF, and a `MSG` line is followed by a payload of the declared length, and a websocket frame may split or join those, so `GrowwNatsBuffer` buffers the stream and hands back only whole messages.
A server `PING` is answered with `PONG`, and an `-ERR` naming an authorization failure is a refused login.

**Quotes.**
`GrowwQuotesSocket` subscribes a price subject and a depth subject per instrument, such as `/ld/eq/nse/price_detailed.2885` and `/ld/eq/nse/book.2885`, with `/ld/fo/...` for derivatives.
Payloads are protobuf `StocksSocketResponseProtoDto` messages, whose classes are built at runtime from Groww's file descriptor, carried here serialized, in a descriptor pool of their own.
Price and depth arrive separately and are merged per instrument.
Prices are in paise and are divided into rupees, and quantities arrive as doubles and are rounded to whole numbers.
An instrument without a name takes the symbol Groww puts in the payload.
The quote socket gives up only after six more failed connects, not on the first refusal after logging in again.

**Order updates.**
`GrowwOrderUpdatesSocket` subscribes the account's subjects, keyed by the subscription id: equity and derivatives orders (`OrderDetailsBroadCastDto`) and derivatives positions (`PositionDetailProto`).
Each message is decoded to a plain dictionary with Groww's own field names, enum fields by name, and every field present even when zero.

Neither socket writes Redis.
The quotes socket hands each frame's ticks to `on_ticks`, and the order socket hands each frame's decoded orders and positions to `on_updates`; the scripts in `bin/groww/` do the writing.
"""

import base64
import json
import threading
import time
import uuid
from datetime import datetime

from stock_brokers.websockets.base import BrokerWebsocket

FEED_URL = "wss://socket-api.groww.in"
SOCKET_TOKEN_URL = "https://api.groww.in/v1/api/apex/v1/socket/token/create/"

PRICE_SUBJECTS = {
    ("CASH", "NSE"): "/ld/eq/nse/price_detailed.",
    ("CASH", "BSE"): "/ld/eq/bse/price_detailed.",
    ("FNO", "NSE"): "/ld/fo/nse/price_detailed.",
    ("FNO", "BSE"): "/ld/fo/bse/price_detailed.",
}
DEPTH_SUBJECTS = {
    ("CASH", "NSE"): "/ld/eq/nse/book.",
    ("CASH", "BSE"): "/ld/eq/bse/book.",
    ("FNO", "NSE"): "/ld/fo/nse/book.",
    ("FNO", "BSE"): "/ld/fo/bse/book.",
}

EQUITY_ORDERS = "stocks/order/updates.apex."
DERIVATIVES_ORDERS = "stocks_fo/order/updates.apex."
DERIVATIVES_POSITIONS = "stocks_fo/position/updates.apex."

DIVISOR = 100.0

AUTHENTICATION_ERRORS = (
    "authorization violation",
    "authentication expired",
    "authentication timeout",
    "user authentication",
)

PING_INTERVAL_SECONDS = 30
PING_TIMEOUT_SECONDS = 10

NKEY_PREFIX_USER = 20 << 3

STOCKS_DESCRIPTOR = (
    "CiZhcGkgdHJhZGluZy9TdG9ja3NTb2NrZXRSZXNwb25zZS5wcm90bxITc3RvY2tzRGF0YS5yZXNwb25zZSInCglCb29rUHJvdG8S"
    "DQoFcHJpY2UYASABKAESCwoDcXR5GAIgASgBIrYCChRTdG9ja3NMaXZlUHJpY2VQcm90bxISCgp0c0luTWlsbGlzGAEgASgBEgwK"
    "BG9wZW4YAiABKAESDAoEaGlnaBgDIAEoARILCgNsb3cYBCABKAESDQoFY2xvc2UYBSABKAESDgoGdm9sdW1lGAYgASgBEg0KBXZh"
    "bHVlGAcgASgBEg4KBmJpZFF0eRgIIAEoARIQCghvZmZlclF0eRgJIAEoARIQCghhdmdQcmljZRgKIAEoARIWCg5oaWdoUHJpY2VS"
    "YW5nZRgLIAEoARIVCg1sb3dQcmljZVJhbmdlGAwgASgBEgsKA2x0cBgNIAEoARIUCgxvcGVuSW50ZXJlc3QYDiABKAESFQoNbG93"
    "VHJhZGVSYW5nZRgPIAEoARIWCg5oaWdoVHJhZGVSYW5nZRgQIAEoASI7ChZTdG9ja3NMaXZlSW5kaWNlc1Byb3RvEhIKCnRzSW5N"
    "aWxsaXMYASABKAESDQoFdmFsdWUYAiABKAEi5QIKFlN0b2Nrc01hcmtldERlcHRoUHJvdG8SEgoKdHNJbk1pbGxpcxgBIAEoARJJ"
    "CgdidXlCb29rGAIgAygLMjguc3RvY2tzRGF0YS5yZXNwb25zZS5TdG9ja3NNYXJrZXREZXB0aFByb3RvLkJ1eUJvb2tFbnRyeRJL"
    "CghzZWxsQm9vaxgDIAMoCzI5LnN0b2Nrc0RhdGEucmVzcG9uc2UuU3RvY2tzTWFya2V0RGVwdGhQcm90by5TZWxsQm9va0VudHJ5"
    "Gk4KDEJ1eUJvb2tFbnRyeRILCgNrZXkYASABKAUSLQoFdmFsdWUYAiABKAsyHi5zdG9ja3NEYXRhLnJlc3BvbnNlLkJvb2tQcm90"
    "bzoCOAEaTwoNU2VsbEJvb2tFbnRyeRILCgNrZXkYASABKAUSLQoFdmFsdWUYAiABKAsyHi5zdG9ja3NEYXRhLnJlc3BvbnNlLkJv"
    "b2tQcm90bzoCOAEiiAMKHFN0b2Nrc1NvY2tldFJlc3BvbnNlUHJvdG9EdG8SDgoGc3ltYm9sGAEgASgJEjcKB3NlZ21lbnQYAiAB"
    "KA4yJi5zdG9ja3NEYXRhLnJlc3BvbnNlLlN0b2NrU2VnbWVudFByb3RvEjkKCGV4Y2hhbmdlGAMgASgOMicuc3RvY2tzRGF0YS5y"
    "ZXNwb25zZS5TdG9ja0V4Y2hhbmdlUHJvdG8SQwoOc3RvY2tMaXZlUHJpY2UYBCABKAsyKS5zdG9ja3NEYXRhLnJlc3BvbnNlLlN0"
    "b2Nrc0xpdmVQcmljZVByb3RvSAASSAoRc3RvY2tzTWFya2V0RGVwdGgYBSABKAsyKy5zdG9ja3NEYXRhLnJlc3BvbnNlLlN0b2Nr"
    "c01hcmtldERlcHRoUHJvdG9IABJIChFzdG9ja3NMaXZlSW5kaWNlcxgGIAEoCzIrLnN0b2Nrc0RhdGEucmVzcG9uc2UuU3RvY2tz"
    "TGl2ZUluZGljZXNQcm90b0gAQgsKCWxpdmVQb2ludCIoChVTdG9ja3NNYXJrZXRJbmZvUHJvdG8SDwoHbWVzc2FnZRgBIAEoCSpZ"
    "ChJTdG9ja0V4Y2hhbmdlUHJvdG8SBwoDQlNFEAASBwoDTlNFEAESBwoDTUNYEAISCQoFTUNYU1gQAxIJCgVOQ0RFWBAEEgoKBkdM"
    "T0JBTBAFEgYKAlVTEAYqQwoRU3RvY2tTZWdtZW50UHJvdG8SCAoEQ0FTSBAAEgcKA0ZOTxABEgwKCENVUlJFTkNZEAISDQoJQ09N"
    "TU9ESVRZEANiBnByb3RvMw=="
)

ORDERS_DESCRIPTOR = (
    "Ch9TdG9ja09yZGVyc1NvY2tldFJlc3BvbnNlLnByb3RvIm4KD1N0b2Nrc0Ftb1N0YXR1cyJbCgRFbnVtEgYKAk5BEAASCwoHUEVO"
    "RElORxABEg4KCkRJU1BBVENIRUQQAhIKCgZQQVJLRUQQAxIKCgZQTEFDRUQQBBIKCgZGQUlMRUQQBRIKCgZNQVJLRVQQBiLnAQoR"
    "U3RvY2tzT3JkZXJTdGF0dXMi0QEKBEVudW0SBwoDTkVXEAASCQoFQUNLRUQQARITCg9UUklHR0VSX1BFTkRJTkcQAhIMCghBUFBS"
    "T1ZFRBADEgwKCFJFSkVDVEVEEAQSCgoGRkFJTEVEEAUSDAoIRVhFQ1VURUQQBhIUChBERUxJVkVSWV9BV0FJVEVEEAcSDQoJQ0FO"
    "Q0VMTEVEEAgSGgoWQ0FOQ0VMTEFUSU9OX1JFUVVFU1RFRBAJEhoKFk1PRElGSUNBVElPTl9SRVFVRVNURUQQChINCglDT01QTEVU"
    "RUQQCyJKChNTdG9ja3NPcmRlckR1cmF0aW9uIjMKBEVudW0SBwoDSU9DEAASBwoDREFZEAESBwoDR1REEAISBwoDR1RDEAMSBwoD"
    "RU9TEAQiUAoNU3RvY2tFeGNoYW5nZSI/CgRFbnVtEgcKA0JTRRAAEgcKA05TRRABEgcKA01DWBACEgkKBU1DWFNYEAMSCQoFTkNE"
    "RVgQBBIGCgJVUxAFIkYKDFN0b2NrU2VnbWVudCI2CgRFbnVtEggKBENBU0gQABIHCgNGTk8QARIMCghDVVJSRU5DWRACEg0KCUNP"
    "TU1PRElUWRADIlUKDVN0b2Nrc1Byb2R1Y3QiRAoERW51bRIHCgNDTkMQABIHCgNNSVMQARIGCgJDTxACEgYKAkJPEAMSCAoETlJN"
    "TBAEEgcKA0FSQhAFEgcKA01URhAGIjsKD1N0b2Nrc09yZGVyVHlwZSIoCgRFbnVtEgcKA01LVBAAEgUKAUwQARIGCgJTTBACEggK"
    "BFNMX00QAyKCAgoVU3RvY2tzVHJhbnNhY3Rpb25UeXBlIugBCgRFbnVtEgwKCElOVEVSTkFMEAASCwoHUEVORElORxABEgkKBUJP"
    "TlVTEAISDAoIQlNFX0JPTFQQAxILCgdOU0VfTk9XEAQSBwoDSVBPEAUSEgoOREVNQVRfVFJBTlNGRVIQBhIRCg1ORVNUX1RFUk1J"
    "TkFMEAcSEgoORVhDSEFOR0VfU0hPUlQQCBILCgdBVUNUSU9OEAkSEgoOSU5URVJOQUxfU0hPUlQQChIKCgZNRVJHRVIQCxIHCgNG"
    "Tk8QDBIMCghCVVlfQkFDSxANEhcKE1BIWVNJQ0FMX1NFVFRMRU1FTlQQDiIlCg1TdG9ja3NCdXlTZWxsIhQKBEVudW0SBQoBQhAA"
    "EgUKAVMQASJdChFTdG9ja3NUcmFkZVN0YXR1cyJICgRFbnVtEgwKCEVYRUNVVEVEEAASFAoQREVMSVZFUllfQVdBSVRFRBABEg0K"
    "CUNPTVBMRVRFRBACEg0KCUNBTkNFTExFRBADIlIKC09yZGVyU291cmNlIkMKBEVudW0SCAoEVVNFUhAAEgoKBlNZU1RFTRABEg0K"
    "CVNNQUxMQ0FTRRACEg4KClNNQVJUT1JERVIQAxIGCgJOQRAEIkUKEVN0YWdlQW5kVGltZVN0YW1wEh0KFXRpbWVTdGFtcEZyb21N"
    "aWROaWdodBgBIAEoARIRCglzdGFnZU5hbWUYAiABKAkifgoYT3JkZXJEZXRhaWxzQnJvYWRDYXN0RHRvEi0KEXN0YWdlQW5kVGlt"
    "ZVN0YW1wGAEgAygLMhIuU3RhZ2VBbmRUaW1lU3RhbXASMwoUb3JkZXJEZXRhaWxVcGRhdGVEdG8YAiABKAsyFS5PcmRlckRldGFp"
    "bFVwZGF0ZUR0byKLBAoUT3JkZXJEZXRhaWxVcGRhdGVEdG8SCwoDcXR5GAEgASgFEg0KBXByaWNlGAIgASgDEhQKDHRyaWdnZXJQ"
    "cmljZRgDIAEoAxIRCglmaWxsZWRRdHkYBCABKAUSFAoMcmVtYWluaW5nUXR5GAUgASgFEhQKDGF2Z0ZpbGxQcmljZRgGIAEoAxIU"
    "Cgxncm93d09yZGVySWQYByABKAkSFwoPZXhjaGFuZ2VPcmRlcklkGAggASgJEiwKC29yZGVyU3RhdHVzGAkgASgOMhcuU3RvY2tz"
    "T3JkZXJTdGF0dXMuRW51bRIrCghkdXJhdGlvbhgKIAEoDjIZLlN0b2Nrc09yZGVyRHVyYXRpb24uRW51bRIlCghleGNoYW5nZRgL"
    "IAEoDjITLlN0b2NrRXhjaGFuZ2UuRW51bRIjCgdzZWdtZW50GAwgASgOMhIuU3RvY2tTZWdtZW50LkVudW0SJAoHcHJvZHVjdBgN"
    "IAEoDjITLlN0b2Nrc1Byb2R1Y3QuRW51bRIoCglvcmRlclR5cGUYDiABKA4yFS5TdG9ja3NPcmRlclR5cGUuRW51bRIkCgdidXlT"
    "ZWxsGA8gASgOMhMuU3RvY2tzQnV5U2VsbC5FbnVtEg4KBnJlbWFyaxgQIAEoCRISCgpjb250cmFjdElkGBYgASgJEhIKCmd1aU9y"
    "ZGVySWQYFyABKAliBnByb3RvMw=="
)

POSITIONS_DESCRIPTOR = (
    "ChRQb3NpdGlvblNvY2tldC5wcm90bxIeZ3Jvd3cucHJvdG9idWYuZm5vLmR0by5mbm9EYXRhIqMBChNQb3NpdGlvbkRldGFpbFBy"
    "b3RvEkMKCnN5bWJvbERhdGEYASABKAsyLy5ncm93dy5wcm90b2J1Zi5mbm8uZHRvLmZub0RhdGEuU3ltYm9sSW5mb1Byb3RvEkcK"
    "DHBvc2l0aW9uSW5mbxgCIAEoCzIxLmdyb3d3LnByb3RvYnVmLmZuby5kdG8uZm5vRGF0YS5Qb3NpdGlvbkluZm9Qcm90byLHAwoP"
    "U3ltYm9sSW5mb1Byb3RvEhMKC3RyVGltZVN0YW1wGAEgASgDEhAKCHNlYXJjaElkGAIgASgJEkQKDXN0b2Nrc1Byb2R1Y3QYAyAB"
    "KA4yLS5ncm93dy5wcm90b2J1Zi5mbm8uZHRvLmZub0RhdGEuU3RvY2tzUHJvZHVjdBISCgpjb250cmFjdElkGAQgASgJEj4KCmVx"
    "dWl0eVR5cGUYBSABKA4yKi5ncm93dy5wcm90b2J1Zi5mbm8uZHRvLmZub0RhdGEuRXF1aXR5VHlwZRITCgtkaXNwbGF5TmFtZRgG"
    "IAEoCRIUCgx1bmRlcmx5aW5nSWQYByABKAkSFAoMbnNlTWFya2V0TG90GAggASgDEhQKDGJzZU1hcmtldExvdBgJIAEoAxJIChN1"
    "bmRlcmx5aW5nQXNzZXRUeXBlGAogASgOMisuZ3Jvd3cucHJvdG9idWYuZm5vLmR0by5mbm9EYXRhLkVxdWl0eUFzc2V0EhEKCWZy"
    "ZWV6ZVF0eRgLIAEoAxI/CghleGNoYW5nZRgMIAEoDjItLmdyb3d3LnByb3RvYnVmLmZuby5kdG8uZm5vRGF0YS5TdG9ja0V4Y2hh"
    "bmdlIpUBChFQb3NpdGlvbkluZm9Qcm90bxISCgpzeW1ib2xJc2luGAEgASgJEjUKA0JTRRgCIAEoCzIoLmdyb3d3LnByb3RvYnVm"
    "LmZuby5kdG8uZm5vRGF0YS5Cc2VQcm90bxI1CgNOU0UYAyABKAsyKC5ncm93dy5wcm90b2J1Zi5mbm8uZHRvLmZub0RhdGEuTnNl"
    "UHJvdG8iWAoIQnNlUHJvdG8SEQoJY3JlZGl0UXR5GAEgASgBEhMKC2NyZWRpdFByaWNlGAIgASgBEhAKCGRlYml0UXR5GAMgASgB"
    "EhIKCmRlYml0UHJpY2UYBCABKAEiWAoITnNlUHJvdG8SEQoJY3JlZGl0UXR5GAEgASgBEhMKC2NyZWRpdFByaWNlGAIgASgBEhAK"
    "CGRlYml0UXR5GAMgASgBEhIKCmRlYml0UHJpY2UYBCABKAEqWwoNU3RvY2tzUHJvZHVjdBIHCgNDTkMQABIHCgNNSVMQARIGCgJD"
    "TxACEgYKAkJPEAMSCAoETlJNTBAEEgcKA0FSQhAFEgcKA01URhAGEgwKCF91bmtub3duEAcqTwoKRXF1aXR5VHlwZRIKCgZTVE9D"
    "S1MQABIKCgZGVVRVUkUQARIKCgZPUFRJT04QAhIHCgNFVEYQAxIJCgVJTkRFWBAEEgkKBUJPTkRTEAUqQAoLRXF1aXR5QXNzZXQS"
    "FwoTRVFVSVRZX0FTU0VUX1NUT0NLUxAAEhgKFEVRVUlUWV9BU1NFVF9JTkRJQ0VTEAEqVAoNU3RvY2tFeGNoYW5nZRIHCgNCU0UQ"
    "ABIHCgNOU0UQARIHCgNNQ1gQAhIJCgVNQ1hTWBADEgkKBU5DREVYEAQSCgoGR0xPQkFMEAUSBgoCVVMQBkI9Cidjb20uZ3Jvd3cu"
    "Zm5vLnNvY2tldC51cGRhdGUuY29tbW9ucy5kdG9CEkZub1NvY2tldFVwZGF0ZUR0b2IGcHJvdG8z"
)


class GrowwSocketRefused(Exception):
    """Groww refused the socket token request, which means the access token is dead."""


class GrowwMessageClasses:
    """
    The protobuf message classes Groww's payloads decode into, built from the embedded file descriptors.
    """

    def stocks_response_class(self):
        """
        The `stocksData.response.StocksSocketResponseProtoDto` class the market feed's payloads decode into.

        Returns:
            type: The message class.
        """
        from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

        pool = descriptor_pool.DescriptorPool()
        pool.Add(descriptor_pb2.FileDescriptorProto.FromString(base64.b64decode("".join(STOCKS_DESCRIPTOR))))
        return message_factory.GetMessageClass(pool.FindMessageTypeByName("stocksData.response.StocksSocketResponseProtoDto"))

    def order_and_position_classes(self):
        """
        The `OrderDetailsBroadCastDto` and `PositionDetailProto` classes the order stream's payloads decode into.

        Returns:
            tuple: The order message class and the position message class.
        """
        from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

        pool = descriptor_pool.DescriptorPool()
        for serialized in (ORDERS_DESCRIPTOR, POSITIONS_DESCRIPTOR):
            pool.Add(descriptor_pb2.FileDescriptorProto.FromString(base64.b64decode("".join(serialized))))
        order_class = message_factory.GetMessageClass(pool.FindMessageTypeByName("OrderDetailsBroadCastDto"))
        position_class = message_factory.GetMessageClass(pool.FindMessageTypeByName("groww.protobuf.fno.dto.fnoData.PositionDetailProto"))
        return order_class, position_class

    def as_dict(self, message):
        """
        A protobuf message as a JSON-ready dictionary: Groww's field names, enums by name, every field present.

        Args:
            message (google.protobuf.message.Message): The decoded message.

        Returns:
            dict: The message.
        """
        from google.protobuf import json_format

        return json_format.MessageToDict(message, preserving_proto_field_name=True, always_print_fields_with_no_presence=True)


class GrowwNkeyPair:
    """
    An ed25519 key pair in NATS NKEY form: the public key as a user NKEY, and nonce signing.

    Attributes:
        public_key (str): The public key as a NATS user NKEY.
    """

    def __init__(self):
        """
        Generates a fresh key pair.

        Returns:
            None: This method returns nothing.
        """
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        self._private_key = Ed25519PrivateKey.generate()
        raw_public = self._private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        body = bytes([NKEY_PREFIX_USER]) + raw_public
        self.public_key = base64.b32encode(body + self._crc16(body).to_bytes(2, "little")).rstrip(b"=").decode()

    def signed_nonce(self, nonce):
        """
        A server nonce signed with the private key, base64url encoded without padding, as NATS expects.

        Args:
            nonce (str | bytes): The nonce from the INFO frame.

        Returns:
            str: The signature.
        """
        if isinstance(nonce, str):
            nonce = nonce.encode()
        signature = self._private_key.sign(nonce)
        return base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

    def _crc16(self, data):
        """
        CRC-16/XMODEM, as NATS computes it over NKEY material.

        Args:
            data (bytes): The bytes to checksum.

        Returns:
            int: The checksum.
        """
        crc = 0
        for byte in data:
            crc = crc ^ (byte << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ 0x1021) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF
        return crc


class GrowwNatsBuffer:
    """
    The NATS byte stream of one connection, buffered so that only whole lines and messages come out.
    """

    def __init__(self):
        """
        Starts with nothing buffered.

        Returns:
            None: This method returns nothing.
        """
        self._buffer = b""

    def feed(self, message):
        """
        Adds a websocket frame to the stream and takes out everything it completed.

        Args:
            message (bytes | str): The frame.

        Returns:
            list[tuple]: In order, `("info", info)` for an INFO line, `("ping",)` for a PING, `("error", line)` for an `-ERR` line, and `("message", subject, payload)` for each whole `MSG`.
        """
        if isinstance(message, str):
            message = message.encode()
        self._buffer = self._buffer + bytes(message)
        events = []
        while True:
            end = self._buffer.find(b"\r\n")
            if end == -1:
                break
            line = self._buffer[:end]
            rest = self._buffer[end + 2:]
            if line.startswith(b"MSG "):
                parts = line.decode("utf-8", errors="replace").split()
                if len(parts) < 4:
                    self._buffer = rest
                    continue
                length = int(parts[-1])
                if len(rest) < length + 2:
                    break
                events.append(("message", parts[1], rest[:length]))
                self._buffer = rest[length + 2:]
                continue

            self._buffer = rest
            if line.startswith(b"INFO "):
                events.append(("info", json.loads(line[5:].decode("utf-8"))))
            elif line == b"PING":
                events.append(("ping",))
            elif line.startswith(b"-ERR"):
                events.append(("error", line.decode("utf-8", errors="replace")))
        return events


class GrowwSession:
    """
    The Groww login every socket authenticates with, logged in again by one socket at a time.
    """

    def __init__(self, logger):
        """
        Constructs `GrowwAPI`, which logs in when the stored session is dead.

        Args:
            logger (logging.Logger): Where logins are reported.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `GrowwAPI` raises when it cannot log in.
        """
        from stock_brokers.api.groww import GrowwAPI

        self._api_class = GrowwAPI
        self._logger = logger
        self._lock = threading.Lock()
        self._groww = GrowwAPI()

    def access_token(self):
        """
        The access token in force now, which may be one another process has just obtained.

        Returns:
            str | None: The token.
        """
        return (self._groww._current_login() or {}).get("access_token")

    def socket_token_payload(self, key_pair):
        """
        Asks Groww for a socket JWT bound to a key pair's public key.

        Args:
            key_pair (GrowwNkeyPair): The connection's key pair.

        Returns:
            dict: The answer's payload, which should carry `token` and `subscriptionId`.

        Raises:
            GrowwSocketRefused: For HTTP 401 or 403, which means the access token is dead.
            requests.HTTPError: For any other error status.
        """
        import requests

        headers = {
            "x-request-id": str(uuid.uuid4()),
            "Authorization": f"Bearer {self.access_token()}",
            "Content-Type": "application/json",
            "x-client-id": "growwapi",
            "x-client-platform": "growwapi-python-client",
        }
        response = requests.post(SOCKET_TOKEN_URL, headers=headers, json={"socketKey": key_pair.public_key}, timeout=30)
        if response.status_code in (401, 403):
            raise GrowwSocketRefused(f"HTTP {response.status_code}: {response.text[:200]}")
        response.raise_for_status()
        payload = response.json()
        return payload.get("payload", payload)

    def log_in_again(self, stale_token):
        """
        Logs in again, unless another socket or process already replaced the token that failed.

        Args:
            stale_token (str | None): The access token the failing connection used.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `GrowwAPI` raises when it cannot log in.
        """
        with self._lock:
            if self.access_token() != stale_token:
                return
            self._log_in()

    def log_in_again_without_checking(self):
        """
        Logs in again whether or not the token was already replaced.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `GrowwAPI` raises when it cannot log in.
        """
        with self._lock:
            self._log_in()

    def _log_in(self):
        """
        Logs in by constructing `GrowwAPI` again; the caller holds the lock.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `GrowwAPI` raises when it cannot log in.
        """
        self._logger.warning("Logging in to Groww again.")
        self._groww = self._api_class()


class GrowwQuotesSocket(BrokerWebsocket):
    """
    One Groww NATS websocket carrying the price and depth of a batch of instruments.
    """

    def __init__(self, name, tokens, names, session, on_ticks, logger):
        """
        Sets up a socket for one batch of instruments.

        Args:
            name (str): The connection's name, for the log.
            tokens (list[str]): The batch of `EXCHANGE|SEGMENT|EXCHANGE_TOKEN` instrument tokens.
            names (dict[str, str]): Each token to the instrument's name, shared between sockets; names the payloads reveal are added to it.
            session (GrowwSession): The shared login.
            on_ticks (callable): Called with each frame's list of ticks that carry a price or a book, on this socket's thread.
            logger (logging.Logger): Where the connection reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(name, logger)
        self._tokens = tokens
        self._names = names
        self._session = session
        self._on_ticks = on_ticks
        self._response_class = GrowwMessageClasses().stocks_response_class()
        self._token = None
        self._key_pair = None
        self._socket_jwt = None
        self._buffer = GrowwNatsBuffer()
        self._subjects = {}
        self._state = {}

    def _gives_up_after_logging_in_again(self, failed_connects):
        """
        Gives up only once six connects in a row have failed, as Groww's quotes loop always has.

        Args:
            failed_connects (int): How many connects in a row have failed since the last login.

        Returns:
            bool: True to give up now.
        """
        return failed_connects >= self.MAX_FAILED_CONNECTS

    def _connect(self):
        """
        Obtains a socket JWT for a fresh key pair, opens the websocket, and blocks until it closes.

        Returns:
            None: This method returns nothing.

        Raises:
            RuntimeError: When the socket token answer carries no token.
        """
        import websocket

        self._token = self._session.access_token()
        self._key_pair = GrowwNkeyPair()
        try:
            payload = self._session.socket_token_payload(self._key_pair)
        except GrowwSocketRefused as exception:
            self._authentication_rejected = True
            self._logger.error(f"{self.name} socket token refused: {exception}")
            return
        if not payload.get("token"):
            raise RuntimeError(f"No token in the Groww socket token response: {str(payload)[:200]}")
        self._socket_jwt = payload["token"]
        self._buffer = GrowwNatsBuffer()
        self._subjects = {}
        self._state = {}
        self._websocket_application = websocket.WebSocketApp(
            FEED_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._websocket_application.run_forever(
            ping_interval=PING_INTERVAL_SECONDS,
            ping_timeout=PING_TIMEOUT_SECONDS,
        )

    def _log_in_again(self):
        """
        Logs in again through the shared session, which skips the login when the token was already replaced.

        Returns:
            None: This method returns nothing.
        """
        self._session.log_in_again(self._token)

    def _on_open(self, websocket_connection):
        """
        Notes the open connection; NATS speaks first, with INFO.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        self._opened = True
        self._logger.info(f"{self.name} opened. Waiting for the NATS INFO frame.")

    def _on_error(self, websocket_connection, error):
        """
        Reports an error.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that failed.
            error (Exception): The error.

        Returns:
            None: This method returns nothing.
        """
        self._logger.error(f"{self.name} error: {error}")

    def _send(self, lines):
        """
        Sends NATS lines, one websocket frame each.

        Args:
            lines (list[str]): The lines.

        Returns:
            None: This method returns nothing.
        """
        for line in lines:
            self._websocket_application.send(line)

    def _on_message(self, websocket_connection, message):
        """
        Consumes a frame as NATS, answers its control lines, and hands on the ticks its messages completed.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the frame arrived on.
            message (bytes | str): The frame.

        Returns:
            None: This method returns nothing.
        """
        delivered = []
        for event in self._buffer.feed(message):
            if event[0] == "info":
                self._authenticate(event[1])
            elif event[0] == "ping":
                self._send(["PONG\r\n"])
            elif event[0] == "error":
                self._on_nats_error(event[1])
            else:
                delivered.append((event[1], event[2]))

        ticks = []
        for subject, payload in delivered:
            token = self._subjects.get(subject)
            if token is None:
                continue
            try:
                state = self._apply_payload(token, payload)
            except Exception as exception:
                self._logger.warning(f"{self.name} could not decode a payload on {subject}: {exception}")
                continue
            tick = self._build_tick(token, state)
            if tick["last_price"] is not None or tick["depth"]["buy"] or tick["depth"]["sell"]:
                ticks.append(tick)
        if ticks:
            self._on_ticks(ticks)

    def _authenticate(self, info):
        """
        Answers INFO with CONNECT and the signed nonce, then subscribes the batch's price and depth subjects.

        Args:
            info (dict): The decoded INFO frame.

        Returns:
            None: This method returns nothing.
        """
        connect = {
            "jwt": self._socket_jwt,
            "sig": self._key_pair.signed_nonce(info.get("nonce", "")),
            "verbose": False,
            "pedantic": False,
            "tls_required": False,
            "lang": "python",
            "version": "1.0.0",
            "protocol": 1,
            "headers": bool(info.get("headers", False)),
            "no_responders": False,
        }
        self._send([f"CONNECT {json.dumps(connect)}\r\n", "PING\r\n"])
        lines = []
        for token in self._tokens:
            exchange, segment, exchange_token = token.split("|")
            for prefixes in (PRICE_SUBJECTS, DEPTH_SUBJECTS):
                subject = f"{prefixes[(segment, exchange)]}{exchange_token}"
                self._subjects[subject] = token
                lines.append(f"SUB {subject} {len(self._subjects)}\r\n")
        self._send(lines)
        self._logger.info(f"{self.name} subscribed to {len(lines)} subject(s) for {len(self._tokens)} instrument(s).")

    def _on_nats_error(self, error):
        """
        Reports a NATS error, and closes the connection when it is an authorization failure.

        Args:
            error (str): The `-ERR` line.

        Returns:
            None: This method returns nothing.
        """
        self._logger.error(f"{self.name} NATS error: {error}")
        for marker in AUTHENTICATION_ERRORS:
            if marker in error.lower():
                self._authentication_rejected = True
                self._websocket_application.close()
                return

    def _apply_payload(self, token, payload):
        """
        Merges one protobuf payload into an instrument's state.

        Args:
            token (str): The instrument's `EXCHANGE|SEGMENT|EXCHANGE_TOKEN`.
            payload (bytes): The protobuf bytes.

        Returns:
            dict: The instrument's merged state.

        Raises:
            google.protobuf.message.DecodeError: When the payload is not a `StocksSocketResponseProtoDto`.
        """
        message = self._response_class.FromString(payload)
        state = self._state.setdefault(token, {})

        if message.HasField("stockLivePrice"):
            live = message.stockLivePrice
            for field in ("tsInMillis", "open", "high", "low", "close", "volume", "value", "bidQty", "offerQty", "avgPrice", "ltp", "openInterest"):
                if getattr(live, field, None):
                    state[field] = getattr(live, field)

        if message.HasField("stocksMarketDepth"):
            book = message.stocksMarketDepth
            state["depth"] = {
                "buy": self._levels(book.buyBook),
                "sell": self._levels(book.sellBook),
            }
            if book.tsInMillis:
                state["tsInMillis"] = book.tsInMillis

        if message.HasField("stocksLiveIndices"):
            indices = message.stocksLiveIndices
            if indices.value:
                state["ltp"] = indices.value
            if indices.tsInMillis:
                state["tsInMillis"] = indices.tsInMillis

        if message.symbol and not self._names.get(token):
            self._names[token] = f"{token.split('|')[0]}:{message.symbol}"
        return state

    def _levels(self, book_map):
        """
        Depth levels from a protobuf book map keyed by level, read in level order.

        Args:
            book_map (google.protobuf.internal.containers.MessageMap): The buy or sell book.

        Returns:
            list[dict]: The levels.
        """
        levels = []
        for _, entry in sorted(book_map.items()):
            levels.append({
                "quantity": self._whole(entry.qty),
                "price": entry.price / DIVISOR,
                "orders": None,
            })
        return levels

    def _price(self, state, key):
        """
        A price from the merged state in rupees.

        Args:
            state (dict): The merged state.
            key (str): The field.

        Returns:
            float | None: The price, or None when the field is missing.
        """
        if state.get(key) is None:
            return None
        return state[key] / DIVISOR

    def _whole(self, value):
        """
        A protobuf double quantity as a whole number.

        Args:
            value (float | None): The quantity.

        Returns:
            int | None: The rounded quantity, or None.
        """
        if value is None:
            return None
        return int(round(value))

    def _build_tick(self, token, state):
        """
        Builds a normalized tick from an instrument's merged state.

        Args:
            token (str): The instrument's `EXCHANGE|SEGMENT|EXCHANGE_TOKEN`.
            state (dict): The merged fields.

        Returns:
            dict: The tick.
        """
        last_price = self._price(state, "ltp")
        close = self._price(state, "close")
        mode = "quote"
        if state.get("depth"):
            mode = "full"
        change = None
        if last_price is not None and close:
            change = (last_price - close) * 100 / close
        exchange_timestamp = None
        if state.get("tsInMillis"):
            exchange_timestamp = int(state["tsInMillis"] / 1000)
        return {
            "id": self._names.get(token) or token,
            "broker": "groww",
            "instrument_token": token,
            "exchange": token.split("|")[0],
            "mode": mode,
            "last_price": last_price,
            "last_quantity": None,
            "average_price": self._price(state, "avgPrice"),
            "volume": self._whole(state.get("volume")),
            "buy_quantity": self._whole(state.get("bidQty")),
            "sell_quantity": self._whole(state.get("offerQty")),
            "ohlc": {
                "open": self._price(state, "open"),
                "high": self._price(state, "high"),
                "low": self._price(state, "low"),
                "close": close,
            },
            "change": change,
            "oi": self._whole(state.get("openInterest")),
            "oi_day_high": None,
            "oi_day_low": None,
            "last_trade_time": None,
            "exchange_timestamp": exchange_timestamp,
            "depth": state.get("depth") or {"buy": [], "sell": []},
            "received_at": time.time(),
        }


class GrowwOrderUpdatesSocket(BrokerWebsocket):
    """
    Groww's order and position update stream for the account, over NATS.
    """

    def __init__(self, session, on_updates, logger):
        """
        Sets up the order updates socket.

        Args:
            session (GrowwSession): The login.
            on_updates (callable): Called on this socket's thread with a frame's decoded orders, its decoded positions and the epoch the frame was received.
            logger (logging.Logger): Where the connection reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__("Order updates socket", logger)
        self._session = session
        self._on_updates = on_updates
        self._message_classes = GrowwMessageClasses()
        self._order_class, self._position_class = self._message_classes.order_and_position_classes()
        self._key_pair = None
        self._socket_jwt = None
        self._subscription_id = None
        self._buffer = GrowwNatsBuffer()

    def _connect(self):
        """
        Obtains a socket JWT and subscription id for a fresh key pair, opens the websocket, and blocks until it closes.

        Returns:
            None: This method returns nothing.

        Raises:
            RuntimeError: When the socket token answer carries no token or no subscription id.
        """
        import websocket

        self._key_pair = GrowwNkeyPair()
        try:
            payload = self._session.socket_token_payload(self._key_pair)
        except GrowwSocketRefused as exception:
            self._authentication_rejected = True
            self._logger.error(f"Socket token refused: {exception}")
            return
        if not payload.get("token") or not payload.get("subscriptionId"):
            raise RuntimeError(f"No token or subscription id in the Groww socket token response: {str(payload)[:200]}")
        self._socket_jwt = payload["token"]
        self._subscription_id = payload["subscriptionId"]
        self._buffer = GrowwNatsBuffer()
        self._websocket_application = websocket.WebSocketApp(
            FEED_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._websocket_application.run_forever(
            ping_interval=PING_INTERVAL_SECONDS,
            ping_timeout=PING_TIMEOUT_SECONDS,
        )

    def _log_in_again(self):
        """
        Logs in again, without checking whether another process already replaced the token.

        Returns:
            None: This method returns nothing.
        """
        self._session.log_in_again_without_checking()

    def _on_open(self, websocket_connection):
        """
        Notes the open connection; NATS speaks first, with INFO.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        self._opened = True
        self._logger.info(f"{self.name} opened. Waiting for the NATS INFO frame.")

    def _on_error(self, websocket_connection, error):
        """
        Reports an error.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that failed.
            error (Exception): The error.

        Returns:
            None: This method returns nothing.
        """
        self._logger.error(f"Order updates error: {error}")

    def _order_subjects(self):
        """
        The subjects carrying this account's equity and derivatives orders.

        Returns:
            list[str]: The subjects.
        """
        return [
            f"{EQUITY_ORDERS}{self._subscription_id}",
            f"{DERIVATIVES_ORDERS}{self._subscription_id}",
        ]

    def _position_subjects(self):
        """
        The subject carrying this account's derivatives positions.

        Returns:
            list[str]: The subjects.
        """
        return [
            f"{DERIVATIVES_POSITIONS}{self._subscription_id}",
        ]

    def _on_message(self, websocket_connection, message):
        """
        Consumes a frame as NATS, answers its control lines, and hands on the orders and positions its messages carried.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the frame arrived on.
            message (bytes | str): The frame.

        Returns:
            None: This method returns nothing.
        """
        received_at = datetime.now().timestamp()
        delivered = []
        for event in self._buffer.feed(message):
            if event[0] == "info":
                self._authenticate(event[1])
            elif event[0] == "ping":
                self._websocket_application.send("PONG\r\n")
            elif event[0] == "error":
                self._on_nats_error(event[1])
            else:
                delivered.append((event[1], event[2]))

        order_subjects = set(self._order_subjects())
        position_subjects = set(self._position_subjects())
        orders = []
        positions = []
        for subject, payload in delivered:
            try:
                if subject in order_subjects:
                    broadcast = self._order_class.FromString(payload)
                    if broadcast.HasField("orderDetailUpdateDto") and broadcast.orderDetailUpdateDto.growwOrderId:
                        orders.append(self._message_classes.as_dict(broadcast))
                elif subject in position_subjects:
                    detail = self._position_class.FromString(payload)
                    if detail.HasField("symbolData"):
                        positions.append(self._message_classes.as_dict(detail))
                else:
                    self._logger.info(f"Ignoring a message on an unexpected subject {subject}.")
            except Exception as exception:
                self._logger.warning(f"Could not decode a payload on {subject}: {type(exception).__name__}: {exception}")
        if orders or positions:
            self._on_updates(orders, positions, received_at)

    def _authenticate(self, info):
        """
        Answers INFO with CONNECT and the signed nonce, then subscribes the account's order and position subjects.

        Args:
            info (dict): The decoded INFO frame.

        Returns:
            None: This method returns nothing.
        """
        connect = {
            "jwt": self._socket_jwt,
            "sig": self._key_pair.signed_nonce(info.get("nonce", "")),
            "verbose": False,
            "pedantic": False,
            "tls_required": False,
            "lang": "python",
            "version": "1.0.0",
            "protocol": 1,
            "headers": bool(info.get("headers", False)),
            "no_responders": False,
        }
        subjects = self._order_subjects() + self._position_subjects()
        lines = [
            f"CONNECT {json.dumps(connect)}\r\n",
            "PING\r\n",
        ]
        index = 1
        for subject in subjects:
            lines.append(f"SUB {subject} {index}\r\n")
            index = index + 1
        for line in lines:
            self._websocket_application.send(line)
        self._logger.info(f"Authenticated and subscribed to {len(subjects)} subject(s). Waiting for updates.")

    def _on_nats_error(self, error):
        """
        Reports a NATS error, and closes the connection when it is an authorization failure.

        Args:
            error (str): The `-ERR` line.

        Returns:
            None: This method returns nothing.
        """
        self._logger.error(f"NATS error: {error}")
        for marker in AUTHENTICATION_ERRORS:
            if marker in error.lower():
                self._authentication_rejected = True
                self._websocket_application.close()
                return
