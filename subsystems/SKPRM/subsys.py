#[(44, 100), (156, 245), (23, 184), (176, 290), (215, 288), (245, 298), (59, 127), (134, 275), (220, 286), (60, 168), (208, 249), (19, 152), (38, 122), (234, 254), (227, 293), (64, 186), (28, 49), (22, 106), (25, 212), (144, 148), (260, 284)]

#we are going to try to replicate a trading strategy discussed from our newsletter
#post: https://hangukquant.substack.com/p/1500-trading-strategy-deconstructed
import json
import numpy as np
import pandas as pd

from scipy.stats import skew

import quantlib.backtest_utils as backtest_utils
import quantlib.indicators_cal as indicators_cal
import quantlib.general_utils as general_utils
import quantlib.diagnostics_utils as diagnostic_utils
import datetime

class Skprm:

    def __init__(self, instruments_config, historical_df, historical_strategy_df, simulation_start, vol_target, brokerage_used, logger):
        self.historical_df = historical_df
        self.historical_strategy_df = historical_strategy_df
        self.simulation_start = simulation_start
        self.vol_target = vol_target #we adopt the volatility targetting risk framework. 
        #https://hangukquant.substack.com/p/volatility-targeting-the-strategy
        #https://hangukquant.substack.com/p/volatility-targeting-the-asset-level
        with open(instruments_config) as f:
            self.instruments_config = json.load(f)
        self.brokerage_used = brokerage_used
        self.sysname = "SKPRM"
        self.logger = logger

    """
    Let's Implement the Strategy `API`: this is what the class Lbmom `promises` to implement other components of the trading system
    We want to implement
    1. Function to get data and indicators specific to strategy
    2. Function to run backtest and get positions
    """

    def extend_historicals(self, instruments, historical_data):
        skew_roll = historical_data[[inst + " % ret" for inst in instruments]].rolling(20).apply(skew)
        #skew_instruments = [i[:-5] for i in skew_roll.columns]
        skew_roll.columns = skew_roll.columns + ' skew'
        historical_data = pd.concat([historical_data, skew_roll], axis=1)
        return historical_data

    def run_simulation(self, historical_data, historical_strategy_df, debug=False, use_disk=False):
        logger = self.logger
        """
        Init Params + Pre-processing
        """
        #lets consider running the strategies on bonds, indices and crypto from the oanda asset universe
        #crypto removed from Oanda, solution is an empty json in config
        instruments = self.instruments_config["fx"] +  self.instruments_config["indices"] + self.instruments_config["commodities"] \
            + self.instruments_config["metals"] + self.instruments_config["bonds"] + self.instruments_config["crypto"]
        if not use_disk:
            historical_strategy_df.set_index('date', inplace=True)
            #historical_strategy_df.index = pd.to_datetime(historical_strategy_df.index, unit='H', dayfirst=True)
            historical_strategy_df.index = pd.to_datetime(historical_strategy_df.index, format='%d-%m-%Y-%H-%M')
            historical_data = historical_data.tail(200)
            #historical_data = historical_data[historical_data.index > historical_strategy_df.index[-1]]
            historical_data = self.extend_historicals(instruments=instruments, historical_data=historical_data)
            
            portfolio_df = pd.DataFrame(index=historical_data[self.simulation_start:].index).reset_index()
            portfolio_df.loc[0, "capital"] = 10000
            is_halted = lambda inst, date: not np.isnan(historical_data.loc[date, "{} active".format(inst)]) and (~historical_data[:date].tail(3)["{} active".format(inst)]).any()
            #this means that in order to `not be a halted asset`, it needs to have actively traded over the all last 3 data points at the minimum

            """
            Run Simulation
            We adopt a risk management technique at asset and strategy level called vol targeting. This in general means that we lever our capital to obtain a certain target
            annualized level of volatility, which is our proxy for risk / exposure. This is controlled by the parameter VOL_TARGET, that we pass from the main driver.
            The relative allocations in a vol target framework is that positions are inversely proportional to their volatility. In other words, a priori we assign the same risk
            to each position, when not taking into account the relative alpha (momentum) strengths

            So we assume 3 different risk/capital allocation techniques
            1. Strategy Vol Targetting (vertical across time)
            2. Asset Vol Targetting (relative across assets)
            3. Voting Systems (Indicating the degree of momentum factor)
            """
            for i in portfolio_df.index:
                date = portfolio_df.loc[i, "date"]
                strat_scalar = 2 #strategy scalar (refer to post)

                tradable = [inst for inst in instruments if not is_halted(inst, date)]
                non_tradable = [inst for inst in instruments if inst not in tradable]


                """
                Get PnL, Scalars
                """
                if i != 0:
                    date_prev = portfolio_df.loc[i - 1 ,"date"]
                    pnl, nominal_ret = backtest_utils.get_backtest_day_stats(portfolio_df, instruments, date, date_prev, i, historical_data)
                    #Obtain strategy scalar
                    strat_scalar = backtest_utils.get_strat_scaler(portfolio_df, lookback=100, vol_target=self.vol_target, idx=i, default=strat_scalar)
                    #now, our strategy leverage / scalar should dynamically equilibriate to achieve target exposure, we see that in fact this is the case!

                portfolio_df.loc[i, "strat scalar"] = strat_scalar

                """
                Get Positions
                """
                for inst in non_tradable:
                    #assign weight and position to 0 if not tradabke
                    portfolio_df.loc[i, "{} units".format(inst)] = 0
                    portfolio_df.loc[i, "{} w".format(inst)] = 0

                skews = {}
                for inst in tradable:
                    skews[inst] = historical_data.loc[date, "{} % ret skew".format(inst)]
                skews = {k:v for k,v in sorted(skews.items(), key=lambda pair:pair[1])}
                quantile_size = int(len(tradable) * 0.25)
                high_skewness = list(skews.keys())[-quantile_size:]
                low_skewness = list(skews.keys())[quantile_size:]

                nominal_total = 0            
                #to understand what is going on in here: https://hangukquant.substack.com/p/volatility-targeting-the-asset-level
                for inst in tradable:
                    forecast = 0
                    forecast = 1 if inst in low_skewness else forecast
                    forecast = -1 if inst in high_skewness else forecast

                    #vol_targeting
                    position_vol_target = (1 / len(tradable)) * portfolio_df.loc[i, "capital"] * self.vol_target / np.sqrt(253) #dollar volatility assigned to a single position
                    inst_price = historical_data.loc[date, "{} close".format(inst)]
                    percent_ret_vol = historical_data.loc[date, "{} % ret vol".format(inst)] if historical_data.loc[:date].tail(20)["{} active".format(inst)].all() else 0.025
                    dollar_volatility = backtest_utils.unit_val_change(inst, inst_price * percent_ret_vol, historical_data, date) #vol in nominal dollar terms of the asset under consideration
                    #what is value of a position? this inst_price is not the same, since different contracts are in different currency
                    position = strat_scalar * forecast * position_vol_target / dollar_volatility 
                    portfolio_df.loc[i, "{} units".format(inst)] = position
                    nominal_total += abs(position * backtest_utils.unit_dollar_value(inst, historical_data, date)) #assuming no FX conversion is required
                
                #we see that for the first date, we manage to obtain the positions for the different assets that we want
                nominal_total = backtest_utils.set_leverage_cap(portfolio_df, instruments, date, i, nominal_total, 10, historical_data)

                for inst in tradable:
                    units = portfolio_df.loc[i, "{} units".format(inst)]
                    nominal_inst = units * backtest_utils.unit_dollar_value(inst, historical_data, date)
                    inst_w = nominal_inst / nominal_total
                    portfolio_df.loc[i, "{} w".format(inst)] = inst_w

                """
                Perform Calculations for Date
                """
                portfolio_df.loc[i, "nominal"] = nominal_total
                portfolio_df.loc[i, "leverage"] = nominal_total / portfolio_df.loc[i, "capital"]
            
            portfolio_df.set_index("date", inplace=True)

            portfolio_df = pd.concat([historical_strategy_df, portfolio_df], axis=0)

            diagnostic_utils.save_backtests(
                portfolio_df=portfolio_df, instruments=instruments, brokerage_used=self.brokerage_used, sysname=self.sysname
            )
            diagnostic_utils.save_diagnostics(
                portfolio_df=portfolio_df, instruments=instruments, brokerage_used=self.brokerage_used, sysname=self.sysname
            )

        else:
            portfolio_df = pd.read_excel("./backtests/{}_{}.xlsx".format(self.brokerage_used, self.sysname)) 

        return portfolio_df, instruments

    def get_subsys_pos(self, debug, use_disk):
        portfolio_df, instruments = self.run_simulation(historical_data=self.historical_df, historical_strategy_df = self.historical_strategy_df, debug=debug, use_disk=use_disk)
        return portfolio_df, instruments