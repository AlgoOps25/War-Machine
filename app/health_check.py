"""
Subsystem Health Check - War Machine Startup Diagnostics

⚠️  STATUS: DIAGNOSTIC UTILITY — NOT PART OF THE LIVE SCAN LOOP
─────────────────────────────────────────────────────────────────
This file is a standalone startup diagnostics helper.
The LIVE health server used by Railway is:
    app/core/health_server.py  ← imported by scanner.py (start_health_server / health_heartbeat)

This file is NOT imported by scanner.py or sniper.py.
It can be run manually for subsystem checks:
    python -m app.health_check
─────────────────────────────────────────────────────────────────

Provides comprehensive health checks for all War Machine subsystems:
- Database connectivity (PostgreSQL analytics)
- Discord alerting
- Data ingestion (WebSocket feeds)
- Regime filter (ADX/VIX monitoring)
- Options intelligence
- Validation layer
- Cache system

Phase: 1.10 - Action Item #5
Author: War Machine Team
Date: March 5, 2026
"""

import os
import sys
from typing import Dict, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class HealthCheck:
    """War Machine subsystem health checker."""
    
    def __init__(self):
        self.results = {}
        self.critical_failed = False
        
    def check_database(self, require: bool = False) -> Dict:
        database_url = os.getenv('DATABASE_URL')
        
        if not database_url:
            result = {
                'status': 'offline',
                'message': 'DATABASE_URL not configured',
                'critical': require,
                'symbol': '✗'
            }
            if require:
                self.critical_failed = True
            return result
        
        try:
            import psycopg2
            conn = psycopg2.connect(database_url)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            
            return {
                'status': 'online',
                'message': 'Connected - Analytics enabled',
                'critical': require,
                'symbol': '✓'
            }
            
        except ImportError:
            result = {
                'status': 'offline',
                'message': 'psycopg2 not installed',
                'critical': require,
                'symbol': '✗'
            }
            if require:
                self.critical_failed = True
            return result
            
        except Exception as e:
            result = {
                'status': 'offline',
                'message': f'Connection failed: {str(e)[:50]}',
                'critical': require,
                'symbol': '✗'
            }
            if require:
                self.critical_failed = True
            return result
    
    def check_discord(self, require: bool = False) -> Dict:
        webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
        
        if not webhook_url:
            result = {
                'status': 'offline',
                'message': 'DISCORD_WEBHOOK_URL not configured',
                'critical': require,
                'symbol': '✗'
            }
            if require:
                self.critical_failed = True
            return result
        
        if not webhook_url.startswith('https://discord.com/api/webhooks/'):
            result = {
                'status': 'offline',
                'message': 'Invalid webhook URL format',
                'critical': require,
                'symbol': '✗'
            }
            if require:
                self.critical_failed = True
            return result
        
        return {
            'status': 'online',
            'message': 'Webhook configured',
            'critical': require,
            'symbol': '✓'
        }
    
    def check_data_feed(self) -> Dict:
        api_key = os.getenv('EODHD_API_KEY')
        
        if not api_key:
            return {
                'status': 'offline',
                'message': 'EODHD_API_KEY not configured',
                'critical': True,
                'symbol': '✗'
            }
        
        return {
            'status': 'online',
            'message': f'API key configured ({api_key[:8]}...)',
            'critical': False,
            'symbol': '✓'
        }
    
    def check_regime_filter(self) -> Dict:
        try:
            from app.regime_filter import RegimeFilter
            return {
                'status': 'online',
                'message': 'ADX/VIX monitoring active',
                'critical': False,
                'symbol': '✓'
            }
        except ImportError:
            return {
                'status': 'unknown',
                'message': 'Module not found (may be inline)',
                'critical': False,
                'symbol': '?'
            }
    
    def check_options_system(self) -> Dict:
        try:
            from app.options import options_intelligence
            return {
                'status': 'online',
                'message': 'Options engine loaded',
                'critical': False,
                'symbol': '✓'
            }
        except ImportError:
            return {
                'status': 'offline',
                'message': 'NOT INTEGRATED',
                'critical': False,
                'symbol': '✗'
            }
    
    def check_validation_system(self) -> Dict:
        try:
            from app.validation import validation
            return {
                'status': 'online',
                'message': 'Validation gates active',
                'critical': False,
                'symbol': '✓'
            }
        except ImportError:
            return {
                'status': 'offline',
                'message': 'NOT INTEGRATED',
                'critical': False,
                'symbol': '✗'
            }
    
    def check_cache_system(self) -> Dict:
        try:
            cache_dir = os.path.join(os.getcwd(), 'cache')
            if os.path.exists(cache_dir):
                return {
                    'status': 'online',
                    'message': 'Cache directory ready',
                    'critical': False,
                    'symbol': '✓'
                }
            else:
                return {
                    'status': 'unknown',
                    'message': 'Cache dir not found (may create on demand)',
                    'critical': False,
                    'symbol': '?'
                }
        except Exception:
            return {
                'status': 'unknown',
                'message': 'Status check failed',
                'critical': False,
                'symbol': '?'
            }


def perform_health_check(require_database: bool = False,
                        require_discord: bool = False,
                        verbose: bool = True) -> Dict:
    checker = HealthCheck()
    
    results = {
        'database':      checker.check_database(require=require_database),
        'discord':       checker.check_discord(require=require_discord),
        'data_feed':     checker.check_data_feed(),
        'regime_filter': checker.check_regime_filter(),
        'options':       checker.check_options_system(),
        'validation':    checker.check_validation_system(),
        'cache':         checker.check_cache_system()
    }
    
    if verbose:
        print_health_banner(results)
    
    return {
        'critical_systems_ok': not checker.critical_failed,
        'subsystems': results,
        'timestamp': datetime.now()
    }


def print_health_banner(results: Dict) -> None:
    banner_width = 70
    print("\n" + "=" * banner_width)
    print("WAR MACHINE BOS/FVG SCANNER - STARTUP HEALTH CHECK".center(banner_width))
    print("=" * banner_width)
    print(f"\n{'SUBSYSTEM':<20} {'STATUS':<15} {'DETAILS':<35}")
    print("-" * banner_width)
    
    subsystem_names = {
        'database':      'DATABASE',
        'discord':       'DISCORD ALERTS',
        'data_feed':     'DATA-INGEST',
        'cache':         'CACHE SYSTEM',
        'regime_filter': 'REGIME-FILTER',
        'options':       'OPTIONS-GATE',
        'validation':    'VALIDATION'
    }
    
    for key, name in subsystem_names.items():
        if key in results:
            result  = results[key]
            symbol  = result['symbol']
            status  = result['status'].upper()
            message = result['message']
            if len(message) > 33:
                message = message[:30] + "..."
            print(f"{symbol} {name:<18} {status:<14} {message}")
    
    print("=" * banner_width)
    critical_failed = any(
        r.get('critical') and r.get('status') == 'offline'
        for r in results.values()
    )
    if critical_failed:
        print("⚠️  CRITICAL SYSTEM FAILURE - Cannot proceed")
    else:
        all_online = all(r.get('status') == 'online' for r in results.values())
        if all_online:
            print("✓ All systems operational")
        else:
            print("⚠️  Some optional systems offline - continuing with reduced functionality")
    print("=" * banner_width)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}")
    print("=" * banner_width + "\n")


def print_session_info(session_start: str, session_end: str,
                      is_premarket: bool, watchlist_size: int = 0) -> None:
    mode = "Pre-Market" if is_premarket else "Live Trading"
    print(f"Trading Session: {session_start} - {session_end} ET")
    print(f"Scanner Mode: {mode}")
    if watchlist_size > 0:
        print(f"Watchlist Size: {watchlist_size} tickers")
    print("\n")


if __name__ == "__main__":
    print("Testing War Machine health checks...\n")
    health_status = perform_health_check(
        require_database=False,
        require_discord=False,
        verbose=True
    )
    print("\nHealth Check Results:")
    print(f"Critical Systems OK: {health_status['critical_systems_ok']}")
    print(f"Timestamp: {health_status['timestamp']}")
    print("\n" + "="*70)
    print_session_info(
        session_start="09:30",
        session_end="16:00",
        is_premarket=False,
        watchlist_size=20
    )
