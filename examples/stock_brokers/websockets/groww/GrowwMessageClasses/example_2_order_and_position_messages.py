"""Builds Groww's order and position protobuf classes and decodes one of each into a dictionary.

The order update stream carries two kinds of protobuf payload: `OrderDetailsBroadCastDto` for equity and derivatives orders and `PositionDetailProto` for derivatives positions. `GrowwMessageClasses.order_and_position_classes` builds both from their file descriptors in one pool and returns them as a pair, and `as_dict` turns a decoded message into the dictionary the order socket hands on.

This program builds an executed INFY buy and a NIFTY call position, serializes and decodes each, and prints selected fields of the dictionaries. It needs no stand-ins.

Notice that the order status and side come out by name (`EXECUTED`, `B`), that the 64 bit price comes out as text, as protobuf JSON always writes 64 bit integers, and that the position keeps its nested `symbolData` and `positionInfo`.

Run it from the project root:

    python examples/stock_brokers/websockets/groww/GrowwMessageClasses/example_2_order_and_position_messages.py
"""


from stock_brokers.websockets.groww import (
    GrowwMessageClasses,
)


class OrderAndPositionMessagesExample:
    """Round-trips one Groww order message and one position message.

    Attributes:
        message_classes (GrowwMessageClasses): The class builder being shown.
    """

    def __init__(self):
        """Builds the class builder.

        Returns:
            None: This method returns nothing.
        """
        self.message_classes = GrowwMessageClasses()

    def run(self):
        """Builds, serializes, decodes and prints an order and a position.

        Returns:
            None: This method returns nothing.
        """
        order_class, position_class = self.message_classes.order_and_position_classes()
        print(f'Classes: {order_class.DESCRIPTOR.full_name} and {position_class.DESCRIPTOR.full_name}')
        broadcast = order_class()
        broadcast.orderDetailUpdateDto.growwOrderId = 'GMK2609250001'
        broadcast.orderDetailUpdateDto.qty = 10
        broadcast.orderDetailUpdateDto.filledQty = 10
        broadcast.orderDetailUpdateDto.price = 150000
        broadcast.orderDetailUpdateDto.orderStatus = 6
        order = self.message_classes.as_dict(order_class.FromString(broadcast.SerializeToString()))
        detail = order['orderDetailUpdateDto']
        print(f"Order {detail['growwOrderId']}: status={detail['orderStatus']} side={detail['buySell']} filled={detail['filledQty']} price={detail['price']!r}")
        position = position_class()
        position.symbolData.contractId = 'NIFTY26SEP25000CE'
        position.symbolData.equityType = 2
        position.positionInfo.NSE.creditQty = 75
        decoded = self.message_classes.as_dict(position_class.FromString(position.SerializeToString()))
        print(f"Position {decoded['symbolData']['contractId']}: type={decoded['symbolData']['equityType']} NSE={decoded['positionInfo']['NSE']}")


if __name__ == '__main__':
    OrderAndPositionMessagesExample().run()
