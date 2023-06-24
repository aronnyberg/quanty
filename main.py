"""
#in order to implement a new strategy, we can simply
1. Add the config files for the brokerage involved and the strategy config
2. Add the model to the main driver by importing the class
3. Edit the alpha generation portion of the logic, and optionally add nominal caps.
4. Adjust weight allocations if manual/static weight schemes are adopted

#to add a new brokerage
1. Add the brokerage class
2. Implement the ServiceClass API and TradeClient API
3. Everything else is the same!

Run in source /Users/aronnyberg/quantvenv/bin/activate
"""
import argparse

import json
import datetime
import pandas as pd

from dateutil.relativedelta import relativedelta

import quantlib.data_utils as du
import quantlib.general_utils as gu
import quantlib.backtest_utils as backtest_utils
import quantlib.diagnostics_utils as diagnostic_utils
from quantlib.printer_utils import Printer as Printer
from quantlib.printer_utils import _Colors as Colors
from quantlib.printer_utils import _Highlights as Highlights

from brokerage.oanda.oanda import Oanda
#from brokerage.darwinex.darwinex import Darwinex
from subsystems.LBMOM.subsys import Lbmom
from subsystems.LSMOM.subsys import Lsmom
from subsystems.SKPRM.subsys import Skprm

from portfolio_allocation import optimal_portfolio
import numpy as np

import logging
logging.basicConfig(filename='app.log', filemode='w', format='%(name)s - %(levelname)s - %(message)s')


with open("config/auth_config.json", "r") as f:
    auth_config = json.load(f)

with open("config/portfolio_config.json", "r") as f:
    portfolio_config = json.load(f)


brokerage_used = portfolio_config["brokerage"]
brokerage_config_path = portfolio_config["brokerage_config"][brokerage_used]
db_file = portfolio_config["database"][brokerage_used]

with open("config/{}".format(brokerage_config_path), "r") as f:
    brokerage_config = json.load(f)

if brokerage_used == "oan":
    brokerage = Oanda(brokerage_config=brokerage_config, auth_config=auth_config)
    #crypto not available by OANDA at the moment
    db_instruments = brokerage_config["fx"] +  brokerage_config["indices"] + brokerage_config["commodities"] + brokerage_config["metals"] + brokerage_config["bonds"]# + brokerage_config["crypto"]
#elif brokerage_used == "dwx":
#    brokerage = Darwinex(brokerage_config=brokerage_config, auth_config=auth_config)
#    db_instruments = brokerage_config["fx"] +  brokerage_config["indices"] + brokerage_config["commodities"]  + brokerage_config["equities"]
else:
    print("unknown brokerage, try again.")
    exit()

def print_inst_details(order_config, is_held, required_change=None, percent_change=None, is_override=None):
    color = Colors.YELLOW if not is_held else Colors.BLUE
    Printer.pretty(left="INSTRUMENT:", centre=order_config["instrument"], color=color)
    Printer.pretty(left="CONTRACT SIZE:", centre=order_config["contract_size"], color=color)
    Printer.pretty(left="OPTIMAL UNITS:", centre=order_config["scaled_units"], color=color)
    Printer.pretty(left="CURRENT UNITS:", centre=order_config["current_units"], color=color)
    Printer.pretty(left="OPTIMAL CONTRACTS:", centre=order_config["optimal_contracts"], color=color)
    Printer.pretty(left="CURRENT CONTRACTS:", centre=order_config["current_contracts"], color=color)
    
    if not is_held:
        Printer.pretty(left="ORDER CHANGE:", centre=order_config["rounded_contracts"], color=Colors.WHITE)
    else:
        Printer.pretty(left="ORDER CHANGE:", centre=required_change, color=Colors.WHITE)
        Printer.pretty(left="% CHANGE:", centre=percent_change, color=Colors.WHITE)
        Printer.pretty(left="INERTIA OVERRIDE:", centre=str(is_override), color=Colors.WHITE)

def print_order_details(contracts):
    Printer.pretty(left="MARKET ORDER:", centre=str(contracts), color=Colors.RED)


def run_simulation(instruments, historical_data, portfolio_vol, subsystems_dict, subsystems_config, brokerage_used, debug=True, use_disk=False):
    test_ranges = []
    for subsystem in subsystems_dict.keys():
        test_ranges.append(subsystems_dict[subsystem]["strat_df"].index)
    start = max(test_ranges, key=lambda x:[0])[0]

    if not use_disk:
        portfolio_df = pd.DataFrame(index=historical_data[start:].index).reset_index()
        portfolio_df.loc[0, "capital"] = 10000

        # combined_strategies = pd.DataFrame()
        # for subsystem in subsystems_config.keys():
        #     each_strategy_backtest = pd.read_excel("./backtests/{}_{}.xlsx".format(brokerage_used, subsystem))
        #     each_strategy_backtest.set_index('date', inplace=True)
        #     each_strategy_backtest = each_strategy_backtest['capital ret']
        #     combined_strategies = pd.concat([combined_strategies, each_strategy_backtest], axis=1)
        # combined_strategies.columns = subsystems_dict.keys()
        # combined_strategies.replace(0, np.nan, inplace=True)
        # combined_strategies.dropna(inplace=True)
        # weights, _, _ = optimal_portfolio(combined_strategies.T)
        # combined_strategies.to_excel("testData.xlsx")


        """
        Run Simulation
        """
        for i in portfolio_df.index:
            date = portfolio_df.loc[i, "date"]
            strat_scalar = 2 #strategy scalar (refer to post)
            """
            Get PnL, Scalars
            """
            if i != 0:
                date_prev = portfolio_df.loc[i - 1 ,"date"]
                pnl, nominal_ret = backtest_utils.get_backtest_day_stats(portfolio_df, instruments, date, date_prev, i, historical_data)
                #Obtain strategy scalar
                strat_scalar = backtest_utils.get_strat_scaler(portfolio_df, lookback=100, vol_target=portfolio_vol, idx=i, default=strat_scalar)

            portfolio_df.loc[i, "strat scalar"] = strat_scalar

            """
            Get Positions
            """
            #applying portfolio/brokerage weighting
            inst_units = {}
            for inst in instruments:
                inst_dict = {}
                for subsystem in subsystems_dict.keys():
                    subdf = subsystems_dict[subsystem]["strat_df"]
                    subunits = subdf.loc[date, "{} units".format(inst)] if "{} units".format(inst) in subdf.columns and date in subdf.index  else 0
                    subscalar = portfolio_df.loc[i, "capital"] / subdf.loc[date, "capital"] if date in subdf.index else 0
                    inst_dict[subsystem] = subunits * subscalar
                inst_units[inst] = inst_dict
            #structure output is inst_units = {'inst':{'brokerage':weighted_instrument_units }}


            # USING MARKOWITZ WEIGHTS
            #adjust across brokerages
            # nominal_total = 0            
            # for inst in instruments:
            #     combined_sizing = 0
            #     for subsystem in subsystems_dict.keys():
            #         #incrementally adding/subtracting the total assets for each instrument by strategy
            #         #combined_sizing += inst_units[inst][subsystem] * subsystems_config[subsystem]
            #         #multiplying by 'weights' (markowitz derived allocations)
            #         combined_sizing += inst_units[inst][subsystem] * weights[list(subsystems_dict.keys()).index(subsystem)]
            #         logging.error(weights[list(subsystems_dict.keys()).index(subsystem)])

            #     position = combined_sizing * strat_scalar
            #     portfolio_df.loc[i, "{} units".format(inst)] = position
            #     if position != 0:
            #         #total gross per asset
            #         nominal_total += abs(position * backtest_utils.unit_dollar_value(inst, historical_data, date))
            

            nominal_total = 0            
            for inst in instruments:
                combined_sizing = 0
                for subsystem in subsystems_dict.keys():
                    combined_sizing += inst_units[inst][subsystem] * subsystems_config[subsystem]
                position = combined_sizing * strat_scalar
                portfolio_df.loc[i, "{} units".format(inst)] = position
                if position != 0:
                    nominal_total += abs(position * backtest_utils.unit_dollar_value(inst, historical_data, date))
            
            # outputting instrument weights (abs(units)/units) giving % of portfolio assets
            for inst in instruments:
                units = portfolio_df.loc[i, "{} units".format(inst)]
                if units != 0:
                    nominal_inst = units * backtest_utils.unit_dollar_value(inst, historical_data, date)
                    inst_w = nominal_inst / nominal_total
                    portfolio_df.loc[i, "{} w".format(inst)] = inst_w
                else:
                    portfolio_df.loc[i, "{} w".format(inst)] = 0

            #each strategy creates it's own leverage, which needs to be capped
            nominal_total = backtest_utils.set_leverage_cap(portfolio_df, instruments, date, i, nominal_total, 10, historical_data)

            """
            Perform Calculations for Date
            """
            portfolio_df.loc[i, "nominal"] = nominal_total
            portfolio_df.loc[i, "leverage"] = nominal_total / portfolio_df.loc[i, "capital"]
            #if True: print(portfolio_df.loc[i])    
        
        portfolio_df.set_index("date", inplace=True)

        diagnostic_utils.save_backtests(
        portfolio_df=portfolio_df, instruments=instruments, brokerage_used=brokerage_used, sysname="CombinedStrategies"
        )
        diagnostic_utils.save_diagnostics(
            portfolio_df=portfolio_df, instruments=instruments, brokerage_used=brokerage_used, sysname="CombinedStrategies"
        )
    else:
        portfolio_df = gu.load_file("./backtests/{}_{}.obj".format(brokerage_used, "_"))

    return portfolio_df


def main():
    """
    Load and Update the Database
    """
    #database_df = gu.load_file("./Data/{}_ohlcv.obj".format(brokerage_used))
    database_df = pd.read_excel("./Data/{}".format(db_file)).set_index("date")
    database_df = database_df.loc[~database_df.index.duplicated(keep="first")] 

    #by default, main does not train the classifier
    run_live_classifier = False
    #if running test , only loads from disk
    # Instantiate the parser
    parser = argparse.ArgumentParser(description="Sets mode for main.py run")
    parser.add_argument("--mode", type=str,
                    help='Optional argument indicating a quick test run (using disk data) or train (run classifier), else runs as normal (loads data, no training)',
                    required = False, default = "")
    args = parser.parse_args()
    mode = args.mode
    if mode == 'test':
        portfolio_config["use_disk"] == True
    if mode == 'train':
        #train the classifier now
        run_live_classifier = True

    use_disk = portfolio_config["use_disk"]
    poll_df = pd.DataFrame()
    for db_inst in db_instruments:
        tries = 0
        again = True
        while again:
            try:
                df = brokerage.get_trade_client().get_hourly_ohlcv(instrument=db_inst, count=50, granularity="H1")
                df.set_index("date", inplace=True)
                #print(db_inst, "\n", df)
                cols = list(map(lambda x: "{} {}".format(db_inst, x), df.columns)) 
                df.columns = cols                
                if len(poll_df) == 0:
                    poll_df[cols] = df
                else:
                    poll_df = poll_df.combine_first(df)
                again = False
            except Exception as err:
                print(err)
                tries += 1
                if tries >=5:
                    again=False
                    print("Check TCP Socket Connection, rerun application")
                    exit()
   
    poll_df = poll_df.tail(50)
    database_df = database_df.loc[:poll_df.index[0]][:-1]
    #database_df = database_df.append(poll_df)
    database_df = pd.concat([database_df, poll_df],axis=0)
    print('01: Appened df')
    #print(database_df)

    #Saving as other file names for now
    database_df.to_excel("./Data/{}".format(db_file))
    #gu.save_file("./Data/{}_ohlcv.obj".format(brokerage_used), database_df)
    #database_df.to_excel("./Data/{}".format(db_file))
    #gu.save_file("./Data/{}_ohlcv.obj".format(brokerage_used), database_df)
    """
    Extend the Database
    """
    database_df = database_df.head(7400).tail(1000)
    #11395
    
    historical_data = du.extend_dataframe(traded=db_instruments, df=database_df, fx_codes=brokerage_config["fx_codes"])
    print('02: extended df')
    """
    Risk Parameters
    """
    VOL_TARGET = portfolio_config["vol_target"]
    #sim_start = datetime.date.today() - relativedelta(months=portfolio_config["sim_months"])
    sim_start = database_df.index[0]

    """
    Get existing positions and capital
    """
    capital = brokerage.get_trade_client().get_account_capital()
    # is in units
    positions = brokerage.get_trade_client().get_account_positions()
    print('03: capital and positions',capital, positions)
    
    """
    Get Position of Subsystems
    """ 
    subsystems_config = portfolio_config["subsystems"][brokerage_used]
    strats = {}


    historical_data.to_excel('historical_data.xlsx')
    for subsystem in subsystems_config.keys():
        if subsystem == "lbmom":
            strat = Lbmom(
                instruments_config=portfolio_config["instruments_config"][subsystem][brokerage_used], 
                historical_df=historical_data, 
                simulation_start=sim_start, 
                vol_target=VOL_TARGET, 
                brokerage_used=brokerage_used
            )
        elif subsystem == "lsmom":
            strat = Lsmom(
                instruments_config=portfolio_config["instruments_config"][subsystem][brokerage_used], 
                historical_df=historical_data, 
                simulation_start=sim_start, 
                vol_target=VOL_TARGET, 
                brokerage_used=brokerage_used
            )
        elif subsystem == "skprm":
            strat = Skprm(
                instruments_config=portfolio_config["instruments_config"][subsystem][brokerage_used], 
                historical_df=historical_data, 
                simulation_start=sim_start, 
                vol_target=VOL_TARGET, 
                brokerage_used=brokerage_used
            )
        else:
            print("unknown strat")
            exit()

        strats[subsystem] = strat
    
    print('04: ran subsystem')
    subsystems_dict = {}
    traded = []
    strategies_inactivated = []

    #variable decides if strategy will be ran today
    run_strat = True
    for k, v in strats.items():
        #print("run: ", k, v)
        strat_df, strat_inst = v.get_subsys_pos(debug=True, use_disk=use_disk)
        run_strat = backtest_utils.run_strategy_classifier(database_df, strat_df, run_live_classifier)
        
        if run_strat:
            traded += strat_inst

            subsystems_dict[k] = {
                "strat_df": strat_df,
                "strat_inst": strat_inst
            }
        else:
            strategies_inactivated.append(k)
    traded = list(set(traded))

    # this is where trades are bundled together, in subsystems_dict
    portfolio_df = run_simulation(traded, historical_data, VOL_TARGET, subsystems_dict, subsystems_config, brokerage_used, debug=True, use_disk=use_disk)
    print('05: ran simulation')

    instruments_held = positions.keys()
    instruments_unheld = [inst for inst in traded if inst not in instruments_held]

    """
    Get Optimal Allocations
    """
    trade_on_date = portfolio_df.index[-1]
    capital_scalar = capital / portfolio_df.loc[trade_on_date, "capital"]
    portfolio_optimal = {}

    for inst in traded:
        unscaled_optimal = portfolio_df.loc[trade_on_date, "{} units".format(inst)]
        scaled_units = unscaled_optimal * capital_scalar
        portfolio_optimal[inst] = {
            "unscaled": unscaled_optimal,
            "scaled_units": scaled_units,
            "rounded_units": round(scaled_units),
            "nominal_exposure": abs(scaled_units * backtest_utils.unit_dollar_value(inst, historical_data, trade_on_date)) if scaled_units != 0 else 0
        }

    #print(json.dumps(portfolio_optimal, indent=4))
    print('06: got optimal allocations')
    """
    Edit Open Positions    
    """
    for inst_held in instruments_held:
        Printer.pretty(left="\n******************************************************", color=Colors.BLUE)
        order_config = brokerage.get_service_client().get_order_specs(
            inst=inst_held,
            units=portfolio_optimal[inst_held]["scaled_units"],
            current_contracts=float(positions[inst_held])
        )
        required_change = round(order_config["rounded_contracts"] - order_config["current_contracts"], 2)
        percent_change = round(abs(required_change / order_config["current_contracts"]), 3)
        is_innertia_overriden = brokerage.get_service_client().is_inertia_override(percent_change=percent_change)
        print_inst_details(order_config, True, required_change, percent_change, is_innertia_overriden)
        if is_innertia_overriden:
            print_order_details(required_change)
            if portfolio_config["order_enabled"]:
                brokerage.get_trade_client().market_order(inst=inst_held, order_config=order_config)
        Printer.pretty(left="******************************************************\n", color=Colors.BLUE)

    print('07: edited open positions')
    """
    Open New positions
    """
    for inst_unheld in instruments_unheld:
        Printer.pretty(left="\n******************************************************", color=Colors.YELLOW)
        order_config = brokerage.get_service_client().get_order_specs(
            inst=inst_unheld,
            units=portfolio_optimal[inst_unheld]["scaled_units"],
            current_contracts=0
        )
        if order_config["rounded_contracts"] != 0:
            print_inst_details(order_config, False)
            print_order_details(order_config["rounded_contracts"])
            if portfolio_config["order_enabled"]:
                brokerage.get_trade_client().market_order(inst=inst_unheld, order_config=order_config)
        Printer.pretty(left="******************************************************\n", color=Colors.YELLOW)

    print('08: opened new positions and finished')

    #desired units

    current_units = sum([abs(i) for i in brokerage.get_trade_client().get_account_positions().values()])
    
    
    print(f"Currently have {current_units} units of gross (abs) exposure")
    
    print(f"Expected to have {sum([abs(i['rounded_units']) for i in portfolio_optimal.values()])} units of gross (abs) exposure, excluding inertia")
    print(f"Expected to have {sum([abs(i['nominal_exposure']) for i in portfolio_optimal.values()])} $ of gross (abs) exposure, excluding inertia")
    print(f"{[i for i in strategies_inactivated]} strategies were deactivated today")

    inactive_strategies_df = pd.read_csv('inactive_strategies.csv')
    inactive_strategies_df.set_index('Date', inplace=True)
    inactive_strategies_df.loc[trade_on_date] = [strategies_inactivated]
    pd.DataFrame(inactive_strategies_df).to_csv('inactive_strategies.csv')

if __name__ == "__main__":
    main()

