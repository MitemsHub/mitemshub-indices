"""Mimic exactly what engine-bridge.ts executePythonSnapshot does."""
import asyncio
import json
import os
import sys
import time

# This is the EXACT PYTHONPATH that the bridge sets
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from synthetic_trader.live.market_snapshot import run_live_snapshot, build_watch_alert

async def test():
    print("Running R_100 sniper (skip_api=True) from project root...")
    start = time.time()
    try:
        snapshot = await run_live_snapshot(
            symbol="R_100",
            warmup_count=100,
            timeframe_sec=60,
            higher_timeframe_sec=300,
            max_live_ticks=15,
            trading_mode="sniper",
            skip_api=True,
        )
        elapsed = time.time() - start
        alert = build_watch_alert(snapshot)
        print(f"Duration: {elapsed:.1f}s")
        print(f"Call: {alert.get('call')}")
        print(f"Guardian state: {alert.get('guardian_state')}")
        print(f"Guardian reason: {alert.get('guardian_reason', '')[:200]}")
        print(f"Trade status: {alert.get('trade_status')}")
        print(f"Confidence: {alert.get('confidence')}")
        print(f"Entry: {alert.get('entry')}")
        print(f"Stop loss: {alert.get('stop_loss')}")
        print(f"Take profit: {alert.get('take_profit')}")
        print(f"Regime: {alert.get('regime')}")
        print(f"Direction: {alert.get('direction_bias')}")
        
        # Check if signal was produced
        if alert.get('entry') is not None:
            print("\n*** SIGNAL PRODUCED! Trade plan should show in dashboard. ***")
        else:
            print("\n*** No signal (stand_aside). Checking reasons... ***")
            reasons = alert.get('reasons', [])
            for r in reasons[:5]:
                print(f"  - {r}")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(test())
