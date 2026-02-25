# (File content with line 1405 removed - showing key section only for brevity)

# The fix is simple: Remove line 1405 which reads:
#     data_manager.update_ticker(ticker)
# 
# This line doesn't exist in data_manager and isn't needed since
# WebSocket handles all live data updates automatically.

# I'll provide the full fixed file...