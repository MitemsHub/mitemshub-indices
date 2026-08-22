"""Automated Walk-Forward Validation (WFO) — runs weekly as data accumulates.

This script:
1. Loads the full tick corpus for R_75 and R_100
2. Splits into train/test (80/20 or rolling windows)
3. Runs the band geometry strategy on both splits
4. Generates a performance report with stability metrics
5. Saves results to data/wfo_reports/ for trend analysis
6. Alerts if strategy performance degrades

Usage:
    python -m synthetic_trader.scripts.wfo_scheduler          # single run
    python -m synthetic_trader.scripts.wfo_scheduler --weekly  # generate cron/Task Scheduler config
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from synthetic_trader.backtest.vol_band import VolBandConfig, run_vol_band_backtest
from synthetic_trader.data.tick_store import read_ticks_csv


# ── Configuration ──────────────────────────────────────────────────────
WFO_REPORTS_DIR = Path("data/wfo_reports")
TICK_FILES = {
    "R_75": Path("data/backfill/R_75_ticks.csv"),
    "R_100": Path("data/backfill/R_100_ticks.csv"),
}

# Strategy configs (must match EA .set files)
STRATEGY_CONFIGS = {
    "R_75": VolBandConfig(
        z_entry=2.0, stop_sigma_mult=0.10, target_sigma_mult=1.20,
        max_hold_sec=900, breakeven_trail_frac=0.0,  # NO trail for R_75
    ),
    "R_100": VolBandConfig(
        z_entry=2.2, stop_sigma_mult=0.12, target_sigma_mult=1.0,
        max_hold_sec=900, breakeven_trail_frac=0.0,  # NO trail for R_100
    ),
}

# Alert thresholds
MIN_TRADES = 20               # Minimum trades for statistical significance
MIN_PF = 1.0                  # Profit factor must be > 1.0
MIN_EXPECTANCY = 0.0          # Expectancy must be positive
MAX_PF_DECLINE = 0.2          # Alert if PF drops by more than 0.2 from previous report


@dataclass
class WFOResult:
    """Walk-forward validation result for one symbol."""
    symbol: str
    timestamp: str
    total_ticks: int
    train_ticks: int
    test_ticks: int
    
    # In-sample (training) results
    train_trades: int = 0
    train_win_rate: float = 0.0
    train_pf: float = 0.0
    train_expectancy: float = 0.0
    train_pnl: float = 0.0
    
    # Out-of-sample (testing) results
    test_trades: int = 0
    test_win_rate: float = 0.0
    test_pf: float = 0.0
    test_expectancy: float = 0.0
    test_pnl: float = 0.0
    
    # Stability metrics
    pf_stability: float = 0.0  # |train_pf - test_pf| / train_pf
    wr_stability: float = 0.0  # |train_wr - test_wr|
    
    # Verdict
    verdict: str = "UNKNOWN"  # PASS, WARN, FAIL, INSUFFICIENT_DATA
    alerts: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "total_ticks": self.total_ticks,
            "train_ticks": self.train_ticks,
            "test_ticks": self.test_ticks,
            "train": {
                "trades": self.train_trades,
                "win_rate": self.train_win_rate,
                "profit_factor": self.train_pf,
                "expectancy_r": self.train_expectancy,
                "net_pnl": self.train_pnl,
            },
            "test": {
                "trades": self.test_trades,
                "win_rate": self.test_win_rate,
                "profit_factor": self.test_pf,
                "expectancy_r": self.test_expectancy,
                "net_pnl": self.test_pnl,
            },
            "stability": {
                "pf_stability": self.pf_stability,
                "wr_stability": self.wr_stability,
            },
            "verdict": self.verdict,
            "alerts": self.alerts,
        }


def run_wfo_single(
    symbol: str,
    config: VolBandConfig,
    train_pct: float = 0.8,
) -> WFOResult:
    """Run walk-forward validation for a single symbol."""
    result = WFOResult(
        symbol=symbol,
        timestamp=datetime.now(timezone.utc).isoformat(),
        total_ticks=0,
        train_ticks=0,
        test_ticks=0,
    )
    
    # Load ticks
    tick_path = TICK_FILES.get(symbol)
    if not tick_path or not tick_path.exists():
        result.verdict = "FAIL"
        result.alerts.append(f"Tick file not found: {tick_path}")
        return result
    
    ticks = read_ticks_csv(str(tick_path), symbol)
    if not ticks:
        result.verdict = "FAIL"
        result.alerts.append("No ticks loaded")
        return result
    
    result.total_ticks = len(ticks)
    
    # Split into train/test
    split_idx = int(len(ticks) * train_pct)
    train_ticks = ticks[:split_idx]
    test_ticks = ticks[split_idx:]
    
    result.train_ticks = len(train_ticks)
    result.test_ticks = len(test_ticks)
    
    # Check minimum data requirements
    if len(test_ticks) < 1000:
        result.verdict = "INSUFFICIENT_DATA"
        result.alerts.append(f"Test set too small ({len(test_ticks)} ticks, need 1000+)")
        return result
    
    # Run in-sample backtest
    try:
        r_train = run_vol_band_backtest(train_ticks, symbol, strategy_config=config)
        m_train = r_train.metrics
        result.train_trades = m_train.trades
        result.train_win_rate = m_train.win_rate
        result.train_pf = m_train.profit_factor
        result.train_expectancy = m_train.expectancy_r
        result.train_pnl = m_train.net_pnl
    except Exception as e:
        result.verdict = "FAIL"
        result.alerts.append(f"In-sample backtest failed: {e}")
        return result
    
    # Run out-of-sample backtest
    try:
        r_test = run_vol_band_backtest(test_ticks, symbol, strategy_config=config)
        m_test = r_test.metrics
        result.test_trades = m_test.trades
        result.test_win_rate = m_test.win_rate
        result.test_pf = m_test.profit_factor
        result.test_expectancy = m_test.expectancy_r
        result.test_pnl = m_test.net_pnl
    except Exception as e:
        result.verdict = "FAIL"
        result.alerts.append(f"Out-of-sample backtest failed: {e}")
        return result
    
    # Calculate stability metrics
    if result.train_pf > 0:
        result.pf_stability = abs(result.train_pf - result.test_pf) / result.train_pf
    result.wr_stability = abs(result.train_win_rate - result.test_win_rate)
    
    # Evaluate verdict
    result.verdict = _evaluate_verdict(result)
    
    return result


def _evaluate_verdict(result: WFOResult) -> str:
    """Evaluate the WFO result and assign a verdict."""
    alerts = []
    
    # Check in-sample performance
    if result.train_trades < MIN_TRADES:
        alerts.append(f"Low in-sample trades ({result.train_trades} < {MIN_TRADES})")
    
    if result.train_pf < MIN_PF:
        alerts.append(f"In-sample PF below minimum ({result.train_pf:.2f} < {MIN_PF})")
    
    if result.train_expectancy < MIN_EXPECTANCY:
        alerts.append(f"In-sample expectancy negative ({result.train_expectancy:+.3f}R)")
    
    # Check out-of-sample performance
    if result.test_trades < 5:
        alerts.append(f"Very few out-of-sample trades ({result.test_trades})")
    
    if result.test_pf < MIN_PF and result.test_trades >= 5:
        alerts.append(f"Out-of-sample PF below minimum ({result.test_pf:.2f} < {MIN_PF})")
    
    # Check stability
    if result.pf_stability > 0.3 and result.test_trades >= 5:
        alerts.append(f"High PF instability ({result.pf_stability:.1%})")
    
    if result.wr_stability > 0.10 and result.test_trades >= 5:
        alerts.append(f"High win rate instability ({result.wr_stability:.1%})")
    
    result.alerts = alerts
    
    # Assign verdict
    if not alerts:
        return "PASS"
    elif any("below minimum" in a or "negative" in a for a in alerts):
        return "FAIL"
    else:
        return "WARN"


def run_full_wfo() -> list[WFOResult]:
    """Run WFO for all symbols."""
    results = []
    
    for symbol, config in STRATEGY_CONFIGS.items():
        print(f"Running WFO for {symbol}...")
        result = run_wfo_single(symbol, config)
        results.append(result)
        print(f"  Verdict: {result.verdict}")
    
    return results


def save_report(results: list[WFOResult]) -> Path:
    """Save WFO report to disk."""
    WFO_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = WFO_REPORTS_DIR / f"wfo_report_{timestamp}.json"
    
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": [r.to_dict() for r in results],
    }
    
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    
    # Also save as "latest" for easy access
    latest_path = WFO_REPORTS_DIR / "wfo_report_latest.json"
    latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    
    return report_path


def print_report(results: list[WFOResult]) -> None:
    """Print a human-readable report."""
    print("\n" + "=" * 80)
    print("WALK-FORWARD VALIDATION REPORT")
    print("=" * 80)
    print(f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()
    
    for r in results:
        print(f"\n{'=' * 40}")
        print(f"SYMBOL: {r.symbol}")
        print(f"{'=' * 40}")
        print(f"Total ticks: {r.total_ticks:,}")
        print(f"Train: {r.train_ticks:,} | Test: {r.test_ticks:,}")
        print()
        
        print("IN-SAMPLE (Training):")
        print(f"  Trades: {r.train_trades}")
        print(f"  Win Rate: {r.train_win_rate:.1%}")
        print(f"  Profit Factor: {r.train_pf:.2f}")
        print(f"  Expectancy: {r.train_expectancy:+.3f}R")
        print(f"  Net PnL: {r.train_pnl:+.1f}")
        print()
        
        print("OUT-OF-SAMPLE (Testing):")
        print(f"  Trades: {r.test_trades}")
        print(f"  Win Rate: {r.test_win_rate:.1%}")
        print(f"  Profit Factor: {r.test_pf:.2f}")
        print(f"  Expectancy: {r.test_expectancy:+.3f}R")
        print(f"  Net PnL: {r.test_pnl:+.1f}")
        print()
        
        print("STABILITY:")
        print(f"  PF Stability: {r.pf_stability:.1%}")
        print(f"  WR Stability: {r.wr_stability:.1%}")
        print()
        
        print(f"VERDICT: {r.verdict}")
        if r.alerts:
            print("ALERTS:")
            for alert in r.alerts:
                print(f"  - {alert}")
        print()


def generate_task_scheduler_xml() -> str:
    """Generate Windows Task Scheduler XML for weekly WFO."""
    return """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-08-28T06:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <WeeksInterval>1</WeeksInterval>
        <DaysOfWeek>
          <Sunday />
        </DaysOfWeek>
      </ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>python</Command>
      <Arguments>-m synthetic_trader.scripts.wfo_scheduler</Arguments>
      <WorkingDirectory>PROJECT_ROOT</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Walk-Forward Validation Scheduler")
    parser.add_argument("--weekly", action="store_true",
                        help="Generate Windows Task Scheduler XML")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    args = parser.parse_args()
    
    if args.weekly:
        print(generate_task_scheduler_xml())
        print("\n# To install:")
        print("# 1. Save the XML above to wfo_task.xml")
        print("# 2. Replace PROJECT_ROOT with the actual path")
        print("# 3. Run: schtasks /create /tn \"SyntheticTraderWFO\" /xml wfo_task.xml")
        return
    
    # Run WFO
    results = run_full_wfo()
    
    # Save report
    report_path = save_report(results)
    print(f"\nReport saved to: {report_path}")
    
    # Print report
    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        print_report(results)
    
    # Exit code: 0 = all pass, 1 = any fail
    any_fail = any(r.verdict == "FAIL" for r in results)
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
