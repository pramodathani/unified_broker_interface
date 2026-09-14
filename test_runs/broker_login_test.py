from stock_brokers.api.dhan import *
from stock_brokers.api.flattrade import *
from stock_brokers.api.fyers import *
from stock_brokers.api.groww import *
from stock_brokers.api.indmoney import *
from stock_brokers.api.kotak import *
from stock_brokers.api.shoonya import *
from stock_brokers.api.stoxkart import *
from stock_brokers.api.wisdom_capital import *
from stock_brokers.api.zerodha import *

def main():
    """Run the broker login test calls against the live broker."""
    # dhan = DhanAPI()
    # flattrade = FlattradeAPI()
    fyers = FyersAPI()
    # groww = GrowwAPI()
    # indmoney = INDMoneyAPI()
    # kotak = KotakAPI()
    # shoonya = ShoonyaAPI()
    # zerodha = ZerodhaAPI()

    stoxkart = StoxkartAPI()
    # wisdom_capital = WisdomCapitalAPI()
    # funds = wisdom_capital.get(f"https://trade.wisdomcapital.in/interactive/user/balance?clientID={wisdom_capital._settings['ucc_code']}")
    # print(funds)

if __name__ == "__main__":
    main()
