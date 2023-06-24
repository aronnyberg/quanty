import json
import pandas as pd
import datetime
import oandapyV20
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.trades as trades
import oandapyV20.endpoints.pricing as pricing
import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.positions as positions
import oandapyV20.endpoints.instruments as instruments

from brokerage.oanda.TradeClient import TradeClient
from brokerage.oanda.ServiceClient import ServiceClient
import json
from brokerage.oanda.oanda import Oanda
import time

brokerage_config_path = "oan_config.json"

with open("config/{}".format(brokerage_config_path), "r") as f:
    brokerage_config = json.load(f)
with open("config/auth_config.json", "r") as f:
    auth_config = json.load(f)

brokerage = Oanda(brokerage_config=brokerage_config, auth_config=auth_config)

db_instruments = brokerage_config["fx"] +  brokerage_config["indices"] + brokerage_config["commodities"] + brokerage_config["metals"] + brokerage_config["bonds"]

database_df = pd.DataFrame()

for inst in db_instruments:
    df = brokerage.get_trade_client().get_hourly_ohlcv(instrument=inst, count=5000, granularity="H1")
    df.set_index('date', inplace=True)
    df.columns = [inst + i for i in [' open', ' high', ' low', ' close', ' volume']]
    database_df = pd.concat([database_df, df], axis=1)
    time.sleep(2)

database_df.to_excel("Data/oan_hourly_ohlcv_og_2.xlsx")