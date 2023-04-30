import brokerage.darwinex.DWX_ZeroMQ_Connector_v2_0_1_RC8 as dwxc


brokerage = dwxc.DWX_ZeroMQ_Connector()
brokerage._DWX_GET_ACCOUNT_DETAILS()
input("lets wait for result...press any key to continue")
result = brokerage._get_response_()
print(result)
