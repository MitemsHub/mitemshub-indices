"""Quick bridge pipeline test — runs the same code path as the Next.js bridge."""
import asyncio
import json
import os
import sys
import time

# Ensure src is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from synthetic_trader.live.market_snapshot import run_live_snapshot, build_watch_alert


async def test_snapshot(symbol: str, trading_mode: str = "sniper"):
    print(f"\n{'='*60}")
    print(f"Testing {symbol} ({trading_mode})")
    print(f"{'='*60}")
    start = time.time()
    try:
        snapshot = await run_live_snapshot(
            symbol=symbol,
            warmup_count=100,
            timeframe_sec=60,
            higher_timeframe_sec=300,
            max_live_ticks=15,
            trading_mode=trading_mode,
            skip_api=True,
        )
        elapsed = time.time() - start
        alert = build_watch_alert(snapshot)
        
        print(f"  Duration: {elapsed:.1f}s")
        print(f"  Call: {alert.get('call')}")
        print(f"  Guardian state: {alert.get('guardian_state')}")
        print(f"  Guardian reason: {alert.get('guardian_reason', '')[:150]}")
        print(f"  Trade status: {alert.get('trade_status')}")
        print(f"  Confidence: {alert.get('confidence')}")
        print(f"  Regime: {alert.get('regime')}")
        print(f"  Direction: {alert.get('direction_bias')}")
        print(f"  Entry: {alert.get('entry')}")
        print(f"  Stop loss: {alert.get('stop_loss')}")
        print(f"  Take profit: {alert.get('take_profit')}")
        print(f"  Why: {str(alert.get('why', ''))[:200]}")
        return alert
    except Exception as e:
        elapsed = time.time() - start
        print(f"  FAILED after {elapsed:.1f}s: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    for symbol in ["R_100", "R_75"]:
        for mode in ["sniper", "active_trader"]:
            await test_snapshot(symbol, mode)
    print(f"\n{'='*60}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
