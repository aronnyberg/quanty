from brokerage.oanda.TradeClient import TradeClient
from brokerage.oanda.ServiceClient import ServiceClient

class Oanda():

    def __init__(self, brokerage_config=None, auth_config=None):
        self.service_client = ServiceClient(brokerage_config=brokerage_config)
        self.trade_client = TradeClient(auth_config=auth_config)
    #lets create a service class and trade class for Oanda

    def get_service_client(self):
        return self.service_client

    def get_trade_client(self):
        return self.trade_client