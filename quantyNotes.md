# Components to sizing:
raw units of each instruments determined in subdf (r) line 123
subunits determined in line 124 (multiplied subdf units by subdf capital / portfolio capital)

get_strat_scaler (backtest_utils) that targets a vol across a srategy
This comes together with combined_sizing to form 'position' in main line 134
Combined sizing is the config determined weighting
position is the units of each insturment

Multiple different ways to impact intra-strategy weighting 
* by subsys inital capital
* By config weights

The whole system runs capital for a 10,000 account, until capital_scaler on line 325 when everything scaled accordingly