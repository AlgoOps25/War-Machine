"""
Correlation Check - Prevents Over-Leverage to Correlated Positions

Prevents taking multiple positions in highly correlated tickers that move together.
Example: AAPL, MSFT, NVDA, QQQ are all tech-heavy and highly correlated.
Taking 4 positions = 4x leverage to same sector move.

Correlation Detection Methods:
  1. Sector grouping (hardcoded tech/finance/energy groups)
  2. Price correlation analysis (optional, requires historical data)
  3. ETF holdings overlap (e.g., QQQ contains AAPL, MSFT, NVDA)

Usage:
  from correlation_check import correlation_checker
  
  if correlation_checker.is_safe_to_add_position('AAPL', ['MSFT', 'GOOGL', 'QQQ']):
      # Safe to add
  else:
      # Too much tech exposure, skip
"""
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass
from utils import config


@dataclass
class CorrelationWarning:
    """Warning about correlated position exposure."""
    ticker: str
    correlated_tickers: List[str]
    sector: str
    exposure_pct: float
    recommendation: str
    reason: str


class CorrelationChecker:
    """
    Correlation-based position risk management.
    
    Prevents over-leverage by:
      - Limiting positions per sector
      - Detecting ETF constituent overlap
      - Identifying highly correlated pairs
    """
    
    # Sector groupings (hardcoded for speed)
    SECTOR_GROUPS = {
        # Mega-cap Tech
        "AAPL": "tech", "MSFT": "tech", "GOOGL": "tech", "GOOG": "tech",
        "AMZN": "tech", "META": "tech", "NVDA": "tech", "TSLA": "tech",
        "AMD": "tech", "NFLX": "tech", "ADBE": "tech", "CRM": "tech",
        "ORCL": "tech", "INTC": "tech", "CSCO": "tech", "AVGO": "tech",
        
        # Finance
        "JPM": "finance", "BAC": "finance", "WFC": "finance", "C": "finance",
        "GS": "finance", "MS": "finance", "BLK": "finance", "SCHW": "finance",
        "AXP": "finance", "V": "finance", "MA": "finance",
        
        # Energy
        "XOM": "energy", "CVX": "energy", "COP": "energy", "SLB": "energy",
        "EOG": "energy", "MPC": "energy", "PSX": "energy",
        
        # Healthcare
        "UNH": "healthcare", "JNJ": "healthcare", "PFE": "healthcare",
        "ABBV": "healthcare", "MRK": "healthcare", "LLY": "healthcare",
        "TMO": "healthcare", "ABT": "healthcare",
        
        # Consumer
        "WMT": "consumer", "HD": "consumer", "COST": "consumer",
        "NKE": "consumer", "MCD": "consumer", "SBUX": "consumer",
        "TGT": "consumer", "LOW": "consumer",
        
        # Industrial
        "CAT": "industrial", "BA": "industrial", "GE": "industrial",
        "UPS": "industrial", "HON": "industrial", "LMT": "industrial",
        
        # Market ETFs (treat as separate sectors)
        "SPY": "spy_etf", "QQQ": "qqq_etf", "IWM": "iwm_etf",
        "DIA": "dia_etf", "VTI": "vti_etf",
    }
    
    # ETF constituent overlap (QQQ holdings)
    QQQ_HOLDINGS = {
        "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META",
        "TSLA", "AVGO", "COST", "NFLX", "AMD", "PEP", "ADBE",
        "CSCO", "TMUS", "INTC", "CMCSA", "TXN", "QCOM"
    }
    
    # Known correlated pairs (move together > 0.8 correlation)
    CORRELATED_PAIRS = [
        ("AAPL", "MSFT"), ("AAPL", "NVDA"), ("MSFT", "NVDA"),
        ("GOOGL", "META"), ("GOOGL", "AMZN"),
        ("JPM", "BAC"), ("JPM", "GS"), ("BAC", "WFC"),
        ("XOM", "CVX"), ("CVX", "COP"),
    ]
    
    def __init__(self, max_sector_exposure_pct: float = None, max_correlated_positions: int = 3):
        """
        Initialize correlation checker.
        
        Args:
            max_sector_exposure_pct: Max % of capital in one sector (default from config)
            max_correlated_positions: Max number of correlated positions (default 3)
        """
        self.max_sector_exposure_pct = max_sector_exposure_pct or config.MAX_SECTOR_EXPOSURE_PCT
        self.max_correlated_positions = max_correlated_positions
        
    def is_safe_to_add_position(
        self,
        ticker: str,
        open_positions: List[Dict],
        proposed_risk_dollars: float = None
    ) -> Tuple[bool, Optional[CorrelationWarning]]:
        """
        Check if safe to add new position without over-exposing to correlated tickers.
        
        Args:
            ticker: Ticker to add
            open_positions: List of currently open positions from position_manager
            proposed_risk_dollars: Dollar risk for new position (optional)
        
        Returns:
            (is_safe: bool, warning: CorrelationWarning or None)
        """
        if not open_positions:
            return (True, None)  # No existing positions, safe to add
        
        # Get sector of proposed ticker
        ticker_sector = self.SECTOR_GROUPS.get(ticker, "other")
        
        # Check 1: Sector exposure
        sector_exposure = self._calculate_sector_exposure(open_positions)
        current_sector_pct = sector_exposure.get(ticker_sector, 0.0)
        
        if current_sector_pct >= self.max_sector_exposure_pct:
            warning = CorrelationWarning(
                ticker=ticker,
                correlated_tickers=self._get_tickers_in_sector(open_positions, ticker_sector),
                sector=ticker_sector,
                exposure_pct=current_sector_pct,
                recommendation="REJECT",
                reason=f"Sector exposure limit reached ({current_sector_pct:.1f}% >= {self.max_sector_exposure_pct:.1f}%)"
            )
            return (False, warning)
        
        # Check 2: Direct correlation pairs
        correlated_open = self._find_correlated_positions(ticker, open_positions)
        if len(correlated_open) >= self.max_correlated_positions:
            warning = CorrelationWarning(
                ticker=ticker,
                correlated_tickers=correlated_open,
                sector=ticker_sector,
                exposure_pct=current_sector_pct,
                recommendation="REJECT",
                reason=f"Too many correlated positions ({len(correlated_open)}/{self.max_correlated_positions})"
            )
            return (False, warning)
        
        # Check 3: QQQ + constituent overlap
        if ticker == "QQQ":
            qqq_constituents_open = [p["ticker"] for p in open_positions if p["ticker"] in self.QQQ_HOLDINGS]
            if len(qqq_constituents_open) >= 2:
                warning = CorrelationWarning(
                    ticker=ticker,
                    correlated_tickers=qqq_constituents_open,
                    sector="qqq_etf",
                    exposure_pct=0.0,
                    recommendation="REJECT",
                    reason=f"QQQ overlaps with {len(qqq_constituents_open)} open positions ({', '.join(qqq_constituents_open[:3])})"
                )
                return (False, warning)
        
        # Check 4: Opening QQQ constituent when QQQ is already open
        if ticker in self.QQQ_HOLDINGS:
            has_qqq_open = any(p["ticker"] == "QQQ" for p in open_positions)
            if has_qqq_open:
                warning = CorrelationWarning(
                    ticker=ticker,
                    correlated_tickers=["QQQ"],
                    sector=ticker_sector,
                    exposure_pct=current_sector_pct,
                    recommendation="WARNING",
                    reason=f"{ticker} is in QQQ (already open) - doubling tech exposure"
                )
                # Allow but warn
                return (True, warning)
        
        # All checks passed
        return (True, None)
    
    def _calculate_sector_exposure(self, open_positions: List[Dict]) -> Dict[str, float]:
        """
        Calculate current exposure % by sector.
        
        Returns:
            {sector: exposure_pct}
        """
        if not open_positions:
            return {}
        
        # Calculate total capital at risk
        total_risk = sum(
            abs(p.get("entry", 0) - p.get("stop", 0)) * p.get("contracts", 0) * 100
            for p in open_positions
        )
        
        if total_risk == 0:
            return {}
        
        # Calculate risk by sector
        sector_risk = {}
        for pos in open_positions:
            ticker = pos["ticker"]
            sector = self.SECTOR_GROUPS.get(ticker, "other")
            
            position_risk = abs(pos.get("entry", 0) - pos.get("stop", 0)) * pos.get("contracts", 0) * 100
            sector_risk[sector] = sector_risk.get(sector, 0) + position_risk
        
        # Convert to percentages
        sector_exposure = {
            sector: (risk / total_risk) * 100
            for sector, risk in sector_risk.items()
        }
        
        return sector_exposure
    
    def _get_tickers_in_sector(self, open_positions: List[Dict], sector: str) -> List[str]:
        """Get list of tickers in specified sector from open positions."""
        return [
            p["ticker"]
            for p in open_positions
            if self.SECTOR_GROUPS.get(p["ticker"], "other") == sector
        ]
    
    def _find_correlated_positions(self, ticker: str, open_positions: List[Dict]) -> List[str]:
        """
        Find open positions correlated with proposed ticker.
        
        Returns:
            List of correlated ticker symbols
        """
        correlated = []
        
        # Check sector match
        ticker_sector = self.SECTOR_GROUPS.get(ticker, "other")
        for pos in open_positions:
            pos_ticker = pos["ticker"]
            pos_sector = self.SECTOR_GROUPS.get(pos_ticker, "other")
            
            # Same sector = correlated
            if pos_sector == ticker_sector and pos_sector != "other":
                correlated.append(pos_ticker)
            
            # Check known correlated pairs
            elif self._is_correlated_pair(ticker, pos_ticker):
                correlated.append(pos_ticker)
        
        return correlated
    
    def _is_correlated_pair(self, ticker1: str, ticker2: str) -> bool:
        """Check if two tickers are in known correlated pairs list."""
        return (ticker1, ticker2) in self.CORRELATED_PAIRS or (ticker2, ticker1) in self.CORRELATED_PAIRS
    
    def get_sector_summary(self, open_positions: List[Dict]) -> str:
        """
        Generate formatted sector exposure summary.
        
        Returns:
            Formatted string with sector breakdown
        """
        if not open_positions:
            return "No open positions"
        
        sector_exposure = self._calculate_sector_exposure(open_positions)
        
        lines = ["Sector Exposure:"]
        for sector, pct in sorted(sector_exposure.items(), key=lambda x: x[1], reverse=True):
            tickers = self._get_tickers_in_sector(open_positions, sector)
            status = "âš ï¸" if pct > self.max_sector_exposure_pct else "âœ…"
            lines.append(f"  {status} {sector.upper()}: {pct:.1f}% ({', '.join(tickers)})")
        
        return "\n".join(lines)
    
    def print_correlation_matrix(self, open_positions: List[Dict]) -> None:
        """Print correlation analysis for current portfolio."""
        if not open_positions:
            print("No open positions\n")
            return
        
        print("\n" + "=" * 70)
        print("CORRELATION ANALYSIS")
        print("=" * 70)
        
        # Sector summary
        print(self.get_sector_summary(open_positions))
        
        # Correlated pairs
        print("\nCorrelated Pairs:")
        tickers = [p["ticker"] for p in open_positions]
        found_pairs = []
        
        for i, t1 in enumerate(tickers):
            for t2 in tickers[i+1:]:
                if self._is_correlated_pair(t1, t2):
                    found_pairs.append(f"  âš ï¸ {t1} <-> {t2} (known correlated pair)")
                elif self.SECTOR_GROUPS.get(t1) == self.SECTOR_GROUPS.get(t2):
                    found_pairs.append(f"  â„¹ï¸ {t1} <-> {t2} (same sector)")
        
        if found_pairs:
            print("\n".join(found_pairs))
        else:
            print("  âœ… No highly correlated pairs detected")
        
        # QQQ overlap
        qqq_open = "QQQ" in tickers
        qqq_constituents = [t for t in tickers if t in self.QQQ_HOLDINGS]
        
        if qqq_open and qqq_constituents:
            print(f"\nâš ï¸ QQQ Overlap: QQQ open + {len(qqq_constituents)} constituents ({', '.join(qqq_constituents)})")
        elif qqq_constituents:
            print(f"\nâ„¹ï¸ QQQ Constituents: {len(qqq_constituents)} ({', '.join(qqq_constituents)})")
        
        print("=" * 70 + "\n")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# GLOBAL INSTANCE
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
correlation_checker = CorrelationChecker()


if __name__ == "__main__":
    # Test correlation checker
    print("Testing Correlation Checker...\n")
    
    # Simulate open positions
    test_positions = [
        {"ticker": "AAPL", "entry": 180.0, "stop": 178.0, "contracts": 2},
        {"ticker": "MSFT", "entry": 420.0, "stop": 415.0, "contracts": 1},
        {"ticker": "NVDA", "entry": 800.0, "stop": 790.0, "contracts": 1},
    ]
    
    # Print correlation matrix
    correlation_checker.print_correlation_matrix(test_positions)
    
    # Test adding correlated ticker
    print("Testing: Can we add GOOGL?")
    safe, warning = correlation_checker.is_safe_to_add_position("GOOGL", test_positions)
    print(f"Safe: {safe}")
    if warning:
        print(f"Warning: {warning.reason}\n")
    
    # Test adding uncorrelated ticker
    print("Testing: Can we add JPM (finance)?")
    safe, warning = correlation_checker.is_safe_to_add_position("JPM", test_positions)
    print(f"Safe: {safe}")
    if warning:
        print(f"Warning: {warning.reason}\n")



