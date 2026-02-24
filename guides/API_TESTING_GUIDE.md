# API Integration Testing Guide

## Quick Start

Run the comprehensive test suite to validate all 6 EODHD API integrations:

```bash
python test_api_integrations.py
```

---

## What Gets Tested

### ✅ Test 1: Dividends & Splits Filter
- Fetches upcoming dividends for AAPL, MSFT, JPM, KO, T
- Checks for stock splits
- Validates 7-day event detection
- Verifies 24-hour cache

**Expected Output:**
- List of dividends with dates and amounts
- Cache statistics
- Pass if API responds (even if no dividends found)

### ✅ Test 2: Extended Hours Framework
- Detects current market session (pre-market, regular, after-hours, closed)
- Returns appropriate scan intervals
- Validates time-based logic

**Expected Output:**
- Current session type
- Scan interval recommendation
- Whether scanner should run now

### ✅ Test 3: Dynamic Screener
- Generates watchlist of top 30 movers
- Finds gap candidates (3%+ movers)
- Tests screener filters (market cap, volume, price)
- Validates 6-hour cache

**Expected Output:**
- 30-ticker watchlist
- Gap candidates (if market hours)
- Cache age and ticker count

**Note:** May return fewer results outside market hours - this is normal.

### ✅ Test 4: Technical Indicators
- Fetches RSI(14) for AAPL, TSLA, SPY
- Retrieves MACD values and signals
- Gets SMA(20) prices
- Calculates multi-indicator scores
- Validates 5-minute cache

**Expected Output:**
- RSI values with overbought/oversold status
- MACD histogram and momentum
- SMA prices
- Bullish/bearish scores

### ✅ Test 5: Bulk Download API
- Downloads EOD data for 5 major stocks
- Fetches previous closes in single API call
- Validates bulk endpoint efficiency

**Expected Output:**
- Bulk EOD records with dates, prices, volumes
- Previous closing prices

**Note:** May have limited data on weekends.

### ✅ Test 6: Exchange Hours & Holiday Detection
- Fetches US exchange details
- Loads 2026 holiday calendar
- Checks if today is a holiday or early close
- Determines if scanner should run
- Finds next trading day

**Expected Output:**
- Trading hours (9:30 AM - 4:00 PM)
- Today's status (regular/holiday/early close)
- Scanner run recommendation
- List of upcoming holidays

---

## Expected Results

### All Tests Pass Scenario
```
######################################################################
#                                                                    #
#            WAR MACHINE - API INTEGRATION TEST SUITE                #
#                                                                    #
######################################################################

Test Started: 09:10:00 PM ET on Sunday, February 22, 2026
Testing 6 EODHD API integrations...
✅ API Key: demo123456...

[... test output ...]

######################################################################
#                           TEST SUMMARY                             #
######################################################################
  Dividends & Splits............................... ✅ PASSED
  Extended Hours................................... ✅ PASSED
  Dynamic Screener................................. ✅ PASSED
  Technical Indicators............................. ✅ PASSED
  Bulk Download.................................... ✅ PASSED
  Exchange Hours................................... ✅ PASSED

----------------------------------------------------------------------
  TOTAL: 6/6 tests passed (100%)
----------------------------------------------------------------------

🎉 ALL TESTS PASSED! Your API integrations are working correctly.
```

### Individual Test Failure
If a test fails:
- Python traceback will show the error
- Check API key is valid
- Verify EODHD plan includes the endpoint
- Check internet connection
- Review rate limits (120 requests/minute)

---

## Troubleshooting

### "EODHD_API_KEY not set"
```bash
# Set in .env file:
EODHD_API_KEY=your_key_here

# Or export temporarily:
export EODHD_API_KEY="your_key_here"
```

### "Module not found" errors
Ensure you're in the War-Machine directory:
```bash
cd War-Machine
python test_api_integrations.py
```

### HTTP 401 Errors
- Invalid or expired API key
- Check your EODHD dashboard: https://eodhd.com/cp/dashboard

### HTTP 403 Errors
- Endpoint not included in your plan
- Free tier doesn't include all endpoints (upgrade to All-In-One)

### Empty Results on Weekends
Normal behavior:
- Screener may return fewer tickers
- Bulk download returns last trading day's data
- Technical indicators cache Friday's values

### Rate Limit (429) Errors
- EODHD limits: 120 requests/minute
- Wait 60 seconds and retry
- Tests are designed to stay under limits

---

## Running Individual Tests

You can test modules individually:

### Test Dividends Filter
```python
from dividends_filter import has_dividend_or_split_soon

has_event, details = has_dividend_or_split_soon("AAPL", days_ahead=7)
print(f"Event: {has_event}, Details: {details}")
```

### Test Dynamic Screener
```python
from dynamic_screener import get_dynamic_watchlist

watchlist = get_dynamic_watchlist(max_tickers=50)
print(f"Watchlist: {watchlist}")
```

### Test Technical Indicators
```python
from technical_indicators import get_rsi, get_macd

rsi = get_rsi("AAPL", period=14)
macd = get_macd("AAPL")
print(f"RSI: {rsi}, MACD: {macd}")
```

### Test Exchange Hours
```python
from exchange_hours import should_scanner_run, is_market_holiday

should_run, reason = should_scanner_run()
print(f"Should run: {should_run}, Reason: {reason}")

is_holiday, name = is_market_holiday()
print(f"Holiday: {is_holiday}, Name: {name}")
```

### Test Bulk Download
```python
from bulk_downloader import download_bulk_eod_data

data = download_bulk_eod_data(exchange="US", symbols_filter=["AAPL", "MSFT"])
print(f"Records: {len(data)}")
```

---

## Next Steps After Testing

1. **All tests pass?** → Ready to integrate into scanner and signal_generator
2. **Some tests fail?** → Check troubleshooting section above
3. **Want more coverage?** → Add your own tickers to test script

### Integration Examples

Once tests pass, you can use these in your strategy:

```python
# In signal_generator.py or scanner.py

from dividends_filter import has_dividend_or_split_soon
from technical_indicators import check_rsi_confirmation, get_multi_indicator_score
from dynamic_screener import get_dynamic_watchlist

# Generate watchlist
watchlist = get_dynamic_watchlist(include_core=True, max_tickers=50)

# Filter out dividend stocks
for ticker in watchlist:
    has_event, details = has_dividend_or_split_soon(ticker, days_ahead=2)
    if has_event:
        print(f"Skipping {ticker}: {details['type']} on {details['date']}")
        continue
    
    # Check indicators
    rsi_ok = check_rsi_confirmation(ticker, "bullish")
    score = get_multi_indicator_score(ticker, "bullish")
    
    if rsi_ok and score['total_score'] >= 1.5:
        print(f"✅ {ticker}: Strong bullish setup")
```

---

## Performance Notes

- **Caching**: All modules cache results to minimize API calls
  - Dividends: 24 hours
  - Screener: 6 hours
  - Indicators: 5 minutes
  - Exchange hours: 24 hours

- **API Efficiency**:
  - Bulk download: 1 call instead of 6000+
  - Screener: 1 call returns 50 tickers
  - Indicators: Server-side calculation (no local CPU)

- **Test Duration**: ~30-60 seconds for full suite (includes API delays)

---

## Support

If tests consistently fail:
1. Check EODHD status page: https://eodhd.com/
2. Review your API plan limits
3. Verify Python dependencies are installed
4. Check firewall/proxy settings

**All modules are production-ready once tests pass.** ✅
