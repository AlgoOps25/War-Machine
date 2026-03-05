# Health Check Integration Guide

## Overview

The War Machine health check system provides comprehensive startup diagnostics for all subsystems:

- ✓ **Database** - PostgreSQL analytics connection
- ✓ **Discord** - Webhook alert configuration  
- ✓ **Data Feed** - EODHD API connectivity
- ✓ **Cache** - File system cache availability
- ✓ **Regime Filter** - ADX/VIX monitoring status
- ? **Options Gate** - Options intelligence integration
- ? **Validation** - Signal validation layer integration

## Quick Start

### Add to Your Scanner Startup

```python
import sys
import os
from app.health_check import perform_health_check, print_session_info

# ──────────────────────────────────────────────────────────
# STEP 1: Run health check before main loop
# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\nWar Machine starting up...")
    
    # Perform comprehensive health check
    health_status = perform_health_check(
        require_database=True,   # CRITICAL: Fail fast if DB unavailable
        require_discord=False,   # OPTIONAL: Continue without Discord
        verbose=True             # Show banner
    )
    
    # Exit if critical systems failed
    if not health_status['critical_systems_ok']:
        print("\n⚠️  CRITICAL SYSTEM FAILURE - Aborting startup")
        print("Check DATABASE_URL environment variable and PostgreSQL connection")
        sys.exit(1)
    
    # Print session info
    print_session_info(
        session_start="09:30",
        session_end="16:00",
        is_premarket=False,
        watchlist_size=len(watchlist)  # Your watchlist
    )
    
    # ──────────────────────────────────────────────────────────
    # STEP 2: Initialize subsystems based on health check
    # ──────────────────────────────────────────────────────────
    
    # Database analytics (if available)
    if health_status['subsystems']['database']['status'] == 'online':
        import psycopg2
        analytics_conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        ANALYTICS_AVAILABLE = True
        print("✓ Analytics tracking ENABLED")
    else:
        analytics_conn = None
        ANALYTICS_AVAILABLE = False
        print("⚠️  Analytics tracking DISABLED")
    
    # Discord alerting (if available)
    if health_status['subsystems']['discord']['status'] == 'online':
        discord_webhook = os.getenv('DISCORD_WEBHOOK_URL')
        DISCORD_ENABLED = True
        print("✓ Discord alerts ENABLED")
    else:
        discord_webhook = None
        DISCORD_ENABLED = False
        print("⚠️  Discord alerts DISABLED")
    
    # ──────────────────────────────────────────────────────────
    # STEP 3: Start main scanner loop
    # ──────────────────────────────────────────────────────────
    print("\n🚀 War Machine operational - starting main loop...\n")
    
    # Your scanner main loop here
    # ...
```

## Sample Output

### All Systems Operational

```
======================================================================
     WAR MACHINE BOS/FVG SCANNER - STARTUP HEALTH CHECK     
======================================================================

SUBSYSTEM            STATUS          DETAILS                            
----------------------------------------------------------------------
✓ DATABASE           ONLINE          Connected - Analytics enabled      
✓ DISCORD ALERTS     ONLINE          Webhook configured                 
✓ DATA-INGEST        ONLINE          API key configured (eod_demo...)   
✓ CACHE SYSTEM       ONLINE          Cache directory ready              
✓ REGIME-FILTER      ONLINE          ADX/VIX monitoring active          
✗ OPTIONS-GATE       OFFLINE         NOT INTEGRATED                     
✗ VALIDATION         OFFLINE         NOT INTEGRATED                     
======================================================================
⚠️  Some optional systems offline - continuing with reduced functionality
======================================================================
Timestamp: 2026-03-05 12:45:00 ET
======================================================================

Trading Session: 09:30 - 16:00 ET
Scanner Mode: Live Trading
Watchlist Size: 20 tickers

✓ Analytics tracking ENABLED
✓ Discord alerts ENABLED

🚀 War Machine operational - starting main loop...
```

### Critical Failure Example

```
======================================================================
     WAR MACHINE BOS/FVG SCANNER - STARTUP HEALTH CHECK     
======================================================================

SUBSYSTEM            STATUS          DETAILS                            
----------------------------------------------------------------------
✗ DATABASE           OFFLINE         DATABASE_URL not configured        
✓ DISCORD ALERTS     ONLINE          Webhook configured                 
✓ DATA-INGEST        ONLINE          API key configured (eod_demo...)   
...
======================================================================
⚠️  CRITICAL SYSTEM FAILURE - Cannot proceed
======================================================================
Timestamp: 2026-03-05 12:45:00 ET
======================================================================

⚠️  CRITICAL SYSTEM FAILURE - Aborting startup
Check DATABASE_URL environment variable and PostgreSQL connection
```

## Environment Variables Required

### Critical (System will not start without these)

```bash
# Data feed API key (ALWAYS REQUIRED)
export EODHD_API_KEY="your_api_key_here"

# Database (REQUIRED if require_database=True)
export DATABASE_URL="postgresql://user:password@host:port/database"
```

### Optional (System will run with reduced functionality)

```bash
# Discord webhook for alerts
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
```

## Configuration Options

### Fail-Fast vs Continue

```python
# Option 1: Strict mode (production)
health_status = perform_health_check(
    require_database=True,   # Exit if DB unavailable
    require_discord=True,    # Exit if Discord not configured
    verbose=True
)

# Option 2: Relaxed mode (development/testing)
health_status = perform_health_check(
    require_database=False,  # Continue without DB
    require_discord=False,   # Continue without Discord
    verbose=True
)

# Option 3: Silent mode (for scripts/cron jobs)
health_status = perform_health_check(
    require_database=False,
    require_discord=False,
    verbose=False  # No banner output
)
```

## Troubleshooting

### Database Connection Failed

**Symptom:**
```
✗ DATABASE           OFFLINE         Connection failed: connection refused
```

**Solutions:**
1. Verify DATABASE_URL environment variable is set
2. Check PostgreSQL is running: `pg_isready -h localhost`
3. Verify connection string format: `postgresql://user:pass@host:port/db`
4. Check firewall/network connectivity
5. Ensure psycopg2 is installed: `pip install psycopg2-binary`

### Discord Webhook Invalid

**Symptom:**
```
✗ DISCORD ALERTS     OFFLINE         Invalid webhook URL format
```

**Solutions:**
1. Verify webhook URL starts with `https://discord.com/api/webhooks/`
2. Get new webhook: Discord Server Settings → Integrations → Webhooks → New Webhook
3. Set environment variable: `export DISCORD_WEBHOOK_URL="..."`

### EODHD API Key Missing

**Symptom:**
```
✗ DATA-INGEST        OFFLINE         EODHD_API_KEY not configured
```

**Solutions:**
1. Sign up at https://eodhistoricaldata.com/
2. Get API key from dashboard
3. Set environment variable: `export EODHD_API_KEY="your_key"`
4. For Railway deployment, add to environment variables in dashboard

### Options/Validation Not Integrated

**Symptom:**
```
✗ OPTIONS-GATE       OFFLINE         NOT INTEGRATED
✗ VALIDATION         OFFLINE         NOT INTEGRATED
```

**This is EXPECTED** - These subsystems exist but are not yet wired into the main scanner.

**Next Steps:**
1. Wire validation layer (see action item #2 in main TODO)
2. Integrate options intelligence (see action item #2)
3. Health check will automatically show ✓ once imports work

## Integration with Railway

### Add to Startup Command

**railway.toml:**
```toml
[build]
cmd = "pip install -r requirements.txt"

[deploy]
startCmd = "python breakout_detector.py"
# Health check runs automatically on import

[env]
EODHD_API_KEY = "your_key"
DATABASE_URL = "postgresql://..."
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/..."
```

### Monitor Logs

The health check banner will appear in Railway logs:

```bash
# View Railway logs
railway logs

# Look for health check banner
# Should see: "WAR MACHINE BOS/FVG SCANNER - STARTUP HEALTH CHECK"
```

## Advanced Usage

### Programmatic Health Checks

```python
from app.health_check import HealthCheck

checker = HealthCheck()

# Check individual subsystems
db_status = checker.check_database(require=True)
print(f"Database: {db_status['status']} - {db_status['message']}")

discord_status = checker.check_discord(require=False)
print(f"Discord: {discord_status['status']} - {discord_status['message']}")

# Check if critical systems failed
if checker.critical_failed:
    print("Critical system failure detected")
    sys.exit(1)
```

### Periodic Health Checks

```python
import time
from app.health_check import perform_health_check

while True:
    # Run scanner cycle
    scan_watchlist()
    
    # Periodic health check every 5 minutes
    if time.time() % 300 < 10:  # Every 5 minutes
        health_status = perform_health_check(verbose=False)
        if not health_status['critical_systems_ok']:
            logger.error("Health check failed - restarting...")
            # Handle reconnection logic
```

## Next Steps

1. ✅ **Completed** - Health check module created
2. ⏳ **Todo** - Integrate into breakout_detector.py startup
3. ⏳ **Todo** - Add to Railway deployment
4. ⏳ **Todo** - Wire validation layer (will show ✓ in health check)
5. ⏳ **Todo** - Wire options intelligence (will show ✓ in health check)

## Support

For issues or questions:
1. Check Railway logs for startup banner
2. Verify all environment variables are set
3. Test database connection separately: `psql $DATABASE_URL`
4. Review [troubleshooting section](#troubleshooting) above
