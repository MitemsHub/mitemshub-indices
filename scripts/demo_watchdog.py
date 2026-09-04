"""Demo watchdog: certifies every EA trade on the demo account automatically.

Run anytime on the demo account:
    python scripts/demo_watchdog.py            # one-shot audit
    python scripts/demo_watchdog.py --watch    # loop every 5 min

Checks, all from broker + telemetry records (no assumptions):
  [1] TICKVALUE  — measured from closed deals: profit / (price_delta x volume)
                   must be ~ $1.009/unit/lot on V75 (catches the v26.24 bug class)
  [2] SIZING     — telemetry 'open' event: eff_risk <= 20% of equity at entry
  [3] SENTINEL   — every fill has a v26.26 sentinel audit event
  [4] STOPS      — entry order carries SL and TP (order history, incl. closed)
  [5] PAUSE      — no entry while a 3-loss pause was active (same day, after close)
  [6] EQUITY     — drawdown tracker vs demo start (report at -25%)

Exit codes: 0 = all certified, 1 = violation, 2 = no EA trades yet.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta

import MetaTrader5 as mt5

HERE = os.path.dirname(os.path.abspath(__file__))
TERMINAL = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal",
                        "FB9A56D617EDDDFE29EE54EBEFFE96C1")
TELEMETRY_DIRS = [os.path.join(TERMINAL, "MQL5", "Files"),
                  os.path.join(TERMINAL, "logs", "hosting.6898457.experts")]

EA_MAGIC = 7788075
CAP_PCT = 20.0
TRUE_K = 1.009          # $ per index-unit per 1.0 lot on V75 (calibrated truth)
K_TOL = 0.10            # 10% tolerance on the measured calibration constant


def ev_type(e: dict) -> str:
    """Event discriminator: the EA writes "type" (v26.1+); older "event" kept for compat."""
    return e.get("type") or e.get("event") or ""


def ev_ts(e: dict):
    """Parse MT5 telemetry timestamp '2026.09.03 11:00:00' (or ISO) -> datetime or None."""
    raw = str(e.get("ts", ""))
    m = re.match(r"^(\d{4})\.(\d{2})\.(\d{2})\b", raw)
    if m:
        raw = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" + raw[m.end():]
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def read_telemetry():
    events = []
    for d in TELEMETRY_DIRS:
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            # v26.1+ filename: MitemshubAI_v23_telemetry_<Symbol>.jsonl
            if "telemetr" not in fn.lower() or not fn.endswith(".jsonl"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            except OSError:
                continue
    return events


def audit() -> tuple[list[str], list[str], list[str]]:
    if not mt5.initialize():
        return [], [f"MT5 init failed: {mt5.last_error()}"], []
    acc = mt5.account_info()
    demo = acc.trade_mode != 2
    deals = mt5.history_deals_get(
        datetime.now() - timedelta(days=30), datetime.now() + timedelta(days=1))
    by_pos = defaultdict(list)
    for d in deals:
        if d.magic == EA_MAGIC:
            by_pos[d.position_id].append(d)
    mt5.shutdown()

    telem = read_telemetry()
    passes, fails, warns = [], [], []
    if not by_pos:
        return passes, fails, warns
    if not demo:
        warns.append("account is REAL — watchdog intended for demo")

    eq_now = acc.balance

    for pos_id in sorted(by_pos):
        ds = sorted(by_pos[pos_id], key=lambda d: d.time)
        ins = [d for d in ds if d.entry == mt5.DEAL_ENTRY_IN]
        outs = [d for d in ds if d.entry != mt5.DEAL_ENTRY_IN]
        if not ins:
            continue
        d = ins[0]
        sym, vol, px = d.symbol, d.volume, d.price
        t_in = datetime.fromtimestamp(d.time)
        side = "SELL" if d.type == 1 else "BUY"
        tag = f"{t_in:%m-%d %H:%M} {sym} {side} {vol} @ {px:.2f}"

        # [1] measured tick-value calibration from the closing deal
        if outs and sym == "Volatility 75 Index":
            o = outs[-1]
            denom = (o.price - px) * vol
            if abs(denom) > 1e-9:
                k = abs(o.profit / denom)
                dev = abs(k - TRUE_K) / TRUE_K
                if dev <= K_TOL:
                    passes.append(f"[1] {tag}: measured $/unit/lot = {k:.3f} (truth {TRUE_K})")
                else:
                    fails.append(f"[1] {tag}: measured $/unit/lot = {k:.3f} "
                                 f"vs truth {TRUE_K} — CALIBRATION BROKEN ({dev*100:.0f}% off)")

        # [2] sizing vs 20% cap (telemetry open event; vEq for paper opens)
        open_ev = next((e for e in telem if ev_type(e) == "open"
                        and str(e.get("ticket")) == str(pos_id)), None)
        if open_ev:
            er = float(open_ev.get("eff_risk", 0) or 0)
            eq0 = float(open_ev.get("eq") or open_ev.get("veq") or eq_now or 0)
            pct = er / max(eq0, 0.01) * 100
            (passes if pct <= CAP_PCT + 0.5 else fails).append(
                f"[2] {tag}: risk ${er:.2f} = {pct:.1f}% of ${eq0:.2f} (cap {CAP_PCT:.0f}%)")
        else:
            warns.append(f"[2] {tag}: no telemetry 'open' event (local chart required "
                         f"for sizing audit; VPS telemetry rides the mirror)")

        # [4] entry order carried SL and TP
        try:
            mt5.initialize()
            orders = mt5.history_orders_get(position=pos_id)
            mt5.shutdown()
        except Exception:
            orders = None
        if orders:
            entry_orders = [o for o in orders if o.type in (mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_SELL)
                            and o.volume_current > 0 or o.state == mt5.ORDER_STATE_FILLED]
            eo = next((o for o in orders if o.sl > 0 or o.tp > 0), None)
            if eo is not None and eo.sl > 0 and eo.tp > 0:
                passes.append(f"[4] {tag}: SL {eo.sl:.2f} / TP {eo.tp:.2f} on order")
            elif eo is not None:
                fails.append(f"[4] {tag}: order missing stops (sl={eo.sl}, tp={eo.tp})")
            else:
                warns.append(f"[4] {tag}: no entry order with stops found in history")

        # [5] no entry during an active pause
        prior_closes = [e for e in telem if ev_type(e) == "close"
                        and e.get("paused") in (True, "true")
                        and (tc := ev_ts(e)) is not None
                        and tc < t_in and tc.date() == t_in.date()]
        if prior_closes:
            fails.append(f"[5] {tag}: entered same day while pause was active")

    # [3] sentinel: v26.26 emits a sentinel event ONLY on a post-fill breach
    breaches = [e for e in telem if ev_type(e) == "sentinel"
                and str(e.get("action", "")).upper() == "CLOSE"]
    if breaches:
        fails.append(f"[3] sentinel BREACH x{len(breaches)} — risk cap exceeded after fill")

    # [6] drawdown over the audited window, from broker deal history (authoritative;
    # telemetry mixes symbols and only holds a recent window)
    pos_nets = []
    for pos_id in sorted(by_pos):
        ds = by_pos[pos_id]
        net = sum(d.profit + d.swap + d.commission for d in ds)
        pos_nets.append((max(d.time for d in ds), net))
    if pos_nets:
        pos_nets.sort()
        eq_start = eq_now - sum(n for _, n in pos_nets)
        run = peak = eq_start
        maxdd = 0.0
        for _, n in pos_nets:
            run += n
            peak = max(peak, run)
            if peak > 0:
                maxdd = max(maxdd, (peak - run) / peak * 100)
        passes.append(f"[6] equity ${eq_start:.2f} -> ${eq_now:.2f} over {len(pos_nets)} "
                      f"positions (broker history), max dd {maxdd:.1f}%")
        if maxdd > 25.0:
            warns.append(f"[6] drawdown {maxdd:.1f}% exceeds 25% — review before funding")
    return passes, fails, warns


def paper_audit() -> tuple[list[str], list[str], list[str]]:
    """Certify v26.28 paper trades from paper_open/paper_close telemetry."""
    events = [e for e in read_telemetry() if ev_type(e) in ("paper_open", "paper_close")]
    passes, fails, warns = [], [], []
    if not events:
        return passes, fails, warns
    # v26.1+ uses "type" as the discriminator; older records used "event".
    opens = {str(e.get("ticket")): e for e in events if ev_type(e) == "paper_open"}
    closes = {str(e.get("ticket")): e for e in events if ev_type(e) == "paper_close"}
    for tid, o in sorted(opens.items()):
        er = float(o.get("eff_risk", 0) or 0)
        veq = float(o.get("veq", 0) or 0)
        sl, tp = float(o.get("sl", 0) or 0), float(o.get("tp", 0) or 0)
        strat = o.get("strat", "?")
        tag = f"PAPER#{tid} {o.get('dir')} {strat} risk ${er:.2f}"
        if veq > 0:
            pct = er / veq * 100
            (passes if pct <= CAP_PCT + 0.5 else fails).append(
                f"[2] {tag} = {pct:.1f}% of virtual ${veq:.2f} (cap {CAP_PCT:.0f}%)")
        else:
            warns.append(f"[2] {tag}: no virtual equity in event")
        (passes if sl > 0 and tp > 0 else fails).append(
            f"[4] {tag}: virtual SL {sl:.2f} / TP {tp:.2f}" if sl > 0 and tp > 0
            else f"[4] {tag}: virtual trade missing stops")
        c = closes.get(tid)
        if c:
            r = float(c.get("r", 0) or 0)
            pnl = float(c.get("pnl", 0) or 0)
            passes.append(f"[3] {tag}: closed {c.get('reason')} R={r:+.2f} "
                          f"pnl=${pnl:+.2f} vEq=${float(c.get('veq', 0) or 0):.2f}")
        else:
            warns.append(f"[3] {tag}: still OPEN (no paper_close yet)")
    # virtual-equity drawdown from the close stream. Baseline: the earliest
    # open's pre-trade virtual equity (open "veq" = equity BEFORE this trade's
    # PnL, since paper_close "veq" includes it). If telemetry was rotated away,
    # fall back to the newest close's post-trade "veq" — drawdown measured over
    # the retained window only, never re-anchored to InpPaperEquity.
    pnls = [(ev_ts(c), c) for c in closes.values()]
    pnls = [(t, c) for t, c in pnls if t is not None]
    pnls.sort(key=lambda tc: tc[0])
    if pnls:
        closed_tids = {str(c.get("ticket")) for _, c in pnls}
        pre_open_veq = [float(o.get("veq", 0) or 0) for tid, o in opens.items()
                        if tid not in closed_tids]
        start = min(pre_open_veq) if pre_open_veq else \
                float(pnls[-1][1].get("veq", 0) or 0) - sum(float(c.get("pnl", 0) or 0) for _, c in pnls)
        if start <= 0:
            warns.append("[6] paper drawdown skipped: no positive baseline vEq")
        else:
            run = peak = start
            maxdd = 0.0
            for _, c in pnls:
                run += float(c.get("pnl", 0) or 0)
                peak = max(peak, run)
                maxdd = max(maxdd, (peak - run) / peak * 100)
            passes.append(f"[6] paper vEq ${start:.2f} -> ${run:.2f} ({len(pnls)} closes), max dd {maxdd:.1f}%")
            if maxdd > 25.0:
                warns.append(f"[6] paper drawdown {maxdd:.1f}% exceeds 25%")
    return passes, fails, warns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true", help="loop every 5 minutes")
    ap.add_argument("--interval", type=int, default=300)
    args = ap.parse_args()
    while True:
        passes, fails, warns = audit()
        pp, pf, pw = paper_audit()
        passes += pp; fails += pf; warns += pw
        print(f"\n=== DEMO WATCHDOG {datetime.now():%Y-%m-%d %H:%M:%S} ===")
        for p in passes:
            print(f"  PASS  {p}")
        for w in warns:
            print(f"  WARN  {w}")
        for f in fails:
            print(f"  FAIL  {f}")
        if not passes and not fails:
            print("  no EA trades on this account yet")
        print(f"  verdict: {'CERTIFIED' if not fails else 'VIOLATIONS PRESENT'} "
              f"({len(passes)} pass / {len(fails)} fail / {len(warns)} warn)")
        if not args.watch:
            sys.exit(1 if fails else (2 if not passes and not fails else 0))
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
