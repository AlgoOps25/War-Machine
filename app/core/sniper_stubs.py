"""
Signal Generation Module - BOS/FVG Detection with Hybrid Detector

PHASE 1.14 (MAR 9, 2026):
- Implemented process_ticker with hybrid BOS detector
- Implemented signal state management (armed/watching)
- Discord alert integration
- Database signal tracking

This replaces the temporary stubs with actual working signal generation.
"""
import logging
from typing import Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

# Global detector instance (preserves state across calls)
_detector = None

# Signal state tracking
_armed_signals = {}  # ticker -> signal dict
_watching_fvgs = {}  # ticker -> FVG waiting for retest

def get_detector():
    """Get or create hybrid detector instance"""
    global _detector
    if _detector is None:
        try:
            from app.signals.hybrid_bos_detector import HybridBOSDetector
            _detector = HybridBOSDetector()
            logger.info("[SIGNAL] ✅ Hybrid BOS detector initialized")
        except Exception as e:
            logger.error(f"[SIGNAL] Failed to load hybrid detector: {e}")
            _detector = None
    return _detector

def process_ticker(ticker: str) -> Optional[Dict]:
    """
    Process a ticker for BOS/FVG signals using hybrid detector.
    
    Args:
        ticker: Stock symbol to process
        
    Returns:
        Signal dictionary if signal detected and confirmed, None otherwise
    """
    try:
        # Get detector
        detector = get_detector()
        if detector is None:
            return None
        
        # Get bar data
        from app.data.data_manager import data_manager
        bars = data_manager.get_bars_from_memory(ticker, limit=50)
        
        if not bars or len(bars) < 30:
            return None
        
        # Run detector
        signal = detector.scan(ticker, bars)
        
        if signal:
            logger.info(
                f"[SIGNAL] 🎯 {ticker} {signal['direction'].upper()} signal | "
                f"Entry: ${signal['entry_price']:.2f} | "
                f"Stop: ${signal['stop_price']:.2f} | "
                f"Grade: {signal['confirmation_grade']} ({signal['confirmation_score']})"
            )
            
            # Send Discord alert
            _send_signal_alert(signal)
            
            # Track in database
            _track_signal(signal)
            
            # Store as armed signal
            _armed_signals[ticker] = signal
            
            return signal
        
        return None
        
    except Exception as e:
        logger.error(f"[SIGNAL] Error processing {ticker}: {e}")
        import traceback
        traceback.print_exc()
        return None

def _send_signal_alert(signal: Dict):
    """Send Discord alert for signal"""
    try:
        from app.discord_helpers import send_simple_message
        
        direction_emoji = "🟢" if signal['direction'] == 'bull' else "🔴"
        grade = signal['confirmation_grade']
        score = signal['confirmation_score']
        
        msg = (
            f"{direction_emoji} **{signal['ticker']} {signal['direction'].upper()} SIGNAL** (Grade: {grade} - {score})\n"
            f"📍 Entry: ${signal['entry_price']:.2f}\n"
            f"🛑 Stop: ${signal['stop_price']:.2f}\n"
            f"🎯 T1: ${signal['target_1']:.2f} | T2: ${signal['target_2']:.2f}\n"
            f"📊 FVG: ${signal['fvg_low']:.2f} - ${signal['fvg_high']:.2f} ({signal['fvg_size_pct']:.2f}%)\n"
            f"🔥 BOS Strength: {signal.get('bos_strength', 0)*100:.2f}%\n"
            f"🕐 {signal['timestamp']}"
        )
        
        send_simple_message(msg)
        logger.info(f"[DISCORD] ✅ Signal alert sent for {signal['ticker']}")
        
    except Exception as e:
        logger.error(f"[DISCORD] Failed to send alert: {e}")

def _track_signal(signal: Dict):
    """Track signal in analytics database"""
    try:
        from app.signals.signal_analytics import signal_tracker
        
        if signal_tracker is None:
            return
        
        # Track signal for analytics
        signal_tracker.track_signal(
            ticker=signal['ticker'],
            signal_type=f"{signal['direction'].upper()}_BOS_FVG",
            entry_price=signal['entry_price'],
            stop_price=signal['stop_price'],
            target_1=signal['target_1'],
            target_2=signal['target_2'],
            confidence=signal['confirmation_score'],
            timestamp=signal['timestamp'],
            metadata={
                'grade': signal['confirmation_grade'],
                'candle_type': signal.get('candle_type', 'unknown'),
                'fvg_size_pct': signal['fvg_size_pct'],
                'bos_strength': signal.get('bos_strength', 0),
                'detector': 'hybrid_bos'
            }
        )
        
        logger.debug(f"[ANALYTICS] Signal tracked for {signal['ticker']}")
        
    except Exception as e:
        logger.error(f"[ANALYTICS] Failed to track signal: {e}")

def clear_armed_signals():
    """
    Clear armed signals state (called at EOD reset).
    """
    global _armed_signals
    count = len(_armed_signals)
    _armed_signals.clear()
    logger.info(f"[SIGNALS] Cleared {count} armed signals")

def clear_watching_signals():
    """
    Clear watching FVGs state (called at EOD reset).
    """
    global _watching_fvgs
    count = len(_watching_fvgs)
    _watching_fvgs.clear()
    logger.info(f"[SIGNALS] Cleared {count} watching FVGs")

def get_armed_signals() -> Dict:
    """Get current armed signals"""
    return _armed_signals.copy()

def get_watching_signals() -> Dict:
    """Get current watching FVGs"""
    return _watching_fvgs.copy()
