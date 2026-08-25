#!/usr/bin/env python3
"""Daily scoreboard: MitemshubAI v22 demo results vs old-logic baselines.

Sources (all optional, combined when present):
  --telem PATH        v22 telemetry JSONL (MQL5\\Files\\MitemshubAI_v22_telemetry.jsonl)
                      -> actual v22 trades + decision/discipline analytics.
  --logs DIR          MT5 terminal logs folder (recursive). Parses [v22]/[v21.1]/[v16.5]
                      Experts lines so a PARALLEL old-build chart acts as a true shadow.
  --engine-glob PAT   Python engine journals (e.g. "journals/forward_demo_*.jsonl")
                      -> historical old-logic baseline from their outcome records.

Honesty rule: shadow entries derived ONLY from v22 sig-events (mom-demoted moments)
are reported as counts/directions, never as invented P&L.

Usage:
  python scripts/daily_scoreboard.py --telem "...jsonl" [--logs DIR] [--engine-glob PAT] [--json OUT]
  python scripts/daily_scoreboard.py --selftest          # verify pipeline on synthetic data
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def dstr(epoch: float) -> str:
    return datetime.fromtimestamp(float(epoch), timezone.utc).strftime("%Y-%m-%d")


def money(x: float) -> str:
    return f"${x:+.2f}"


def week_of(d: str) -> str:
    try:
        dt = datetime.strptime(d, "%Y-%m-%d").date()
    except ValueError:
        return d
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def fold_weeks(days: dict) -> dict:
    """Fold a date-keyed day-map into ISO-week totals."""
    wk: dict[str, dict] = {}
    for d, v in sorted(days.items()):
        t = wk.setdefault(week_of(d), {"trades": 0, "wins": 0, "losses": 0,
                                      "r": 0.0, "pnl": 0.0})
        for k in ("trades", "wins", "losses", "r", "pnl"):
            t[k] += v.get(k, 0)
    return wk


PROMOTION_RULES = {
    ">=20 v22 demo trades": lambda s: s["trades"] >= 20,
    "expectancy >= +0.15R": lambda s: (s["r"] / s["trades"] if s["trades"] else 0) >= 0.15,
    "total R positive": lambda s: s["r"] > 0,
}


def promotion_verdict(days_v22: dict, baseline_r):
    s = {"trades": sum(v.get("trades", 0) for v in days_v22.values()),
         "r": sum(v.get("r", 0.0) for v in days_v22.values())}
    print("\n" + "=" * 78)
    print("PROMOTION VERDICT (live-readiness on accumulated demo data)")
    print("=" * 78)
    if not s["trades"]:
        print("No v22 telemetry yet - nothing to judge.")
        return
    rules = dict(PROMOTION_RULES)
    if baseline_r is not None:
        rules["beats old-logic baseline"] = lambda st: st["r"] > baseline_r
    fails = []
    for label, fn in rules.items():
        ok = fn(s)
        print(f"  [{'x' if ok else ' '}] {label:<28}")
        if not ok:
            fails.append(label)
    exp = s["r"] / s["trades"]
    print(f"\n  totals: {s['trades']} trades, {s['r']:+.2f}R ({exp:+.3f}R/trade)"
          + (f" vs old-logic {baseline_r:+.2f}R" if baseline_r is not None else ""))
    print("  >>> PROMOTE CANDIDATE - start sizing up live" if not fails
          else f"  >>> HOLD ON DEMO - unmet: {'; '.join(fails)}")


# ---------------------------------------------------------------- telemetry
def load_telem(path: str) -> list[dict]:
    ev = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "epoch" not in r and "ts" in r:
                try:
                    r["epoch"] = datetime.strptime(r["ts"], "%Y.%m.%d %H:%M:%S").replace(
                        tzinfo=timezone.utc).timestamp()
                except ValueError:
                    continue
            if "epoch" in r:
                ev.append(r)
    ev.sort(key=lambda r: r.get("epoch", 0))
    return ev


def summarize_v22(events: list[dict]) -> dict[str, dict]:
    """Daily v22 trade results from open/close pairs keyed by ticket."""
    days: dict[str, dict] = {}
    opens: dict[int, dict] = {}

    def day(d: str) -> dict:
        return days.setdefault(d, {
            "trades": 0, "wins": 0, "losses": 0, "r": 0.0, "pnl": 0.0,
            "reasons": collections.Counter(), "band": 0,
            "z_abs": [], "open_now": 0})

    for e in events:
        t, tick = e.get("type"), e.get("ticket")
        if t == "close":
            d = day(dstr(e["epoch"]))
            r = float(e.get("r", 0.0))
            o = opens.pop(int(tick), {}) if tick else {}
            d["trades"] += 1
            d["r"] += r
            d["pnl"] += float(e.get("pnl", 0.0))
            d["reasons"][str(e.get("reason", "?"))] += 1
            if r > 0:
                d["wins"] += 1
            elif r < 0:
                d["losses"] += 1
            if o.get("band"):
                d["band"] += 1
            if o.get("z") is not None:
                d["z_abs"].append(abs(float(o["z"])))
        elif t == "open":
            day(dstr(e["epoch"]))["open_now"] += 1
            if tick:
                opens[int(tick)] = e
    for d in days.values():
        d["avg_z"] = sum(d["z_abs"]) / len(d["z_abs"]) if d["z_abs"] else 0.0
    return days


def shadow_from_sigs(events: list[dict]) -> dict[str, dict]:
    """Where the OLD logic would have traded: lone-momentum moments (its whole
    entry model). Reported as counts only - never invented P&L."""
    days: dict[str, dict] = {}
    for e in events:
        if e.get("type") != "sig":
            continue
        d = days.setdefault(dstr(e["epoch"]), {
            "evals": 0, "take": 0, "skip": 0,
            "skips": collections.Counter(), "mom_alone": 0,
            "mom_up": 0, "mom_down": 0, "bf_take": 0})
        d["evals"] += 1
        legs = str(e.get("legs", ""))
        act = str(e.get("action", "SKIP"))
        if act == "TAKE":
            d["take"] += 1
            if "BF" in legs:
                d["bf_take"] += 1
        else:
            d["skip"] += 1
            d["skips"][str(e.get("reason", "?"))[:34]] += 1
        if "MOM" in legs:
            if act == "SKIP":
                d["mom_alone"] += 1
            if "MOM+" in legs:
                d["mom_up"] += 1
            if "MOM-" in legs:
                d["mom_down"] += 1
    return days


# ------------------------------------------------------------- experts logs
LOG_TS_RE = re.compile(r"^(\d{4}\.\d{2}\.\d{2}) \d{2}:\d{2}:\d{2}")
OPEN_RE = re.compile(r"\[(v[\d.]+)\] \S*?(BUY|SELL) @")
CLOSE_RE = re.compile(r"\[(v[\d.]+)\] CLOSE \S+ R=([+-]?\d+\.?\d*)")


def parse_expert_logs(logdir: str) -> dict[str, dict[str, dict]]:
    """Per version-tag daily trades/R from MT5 Experts .log files."""
    out: dict[str, dict[str, dict]] = {}
    for fp in glob.glob(os.path.join(logdir, "**", "*.log"), recursive=True):
        try:
            raw = Path(fp).read_bytes()
        except OSError:
            continue
        text = raw.decode("utf-16-le", errors="ignore")
        if "[" not in text or "v" not in text:
            text = raw.decode("utf-8", errors="ignore")
        for line in text.splitlines():
            m = LOG_TS_RE.match(line)
            if not m:
                continue
            date = m.group(1).replace(".", "-")
            om = OPEN_RE.search(line)
            cm = CLOSE_RE.search(line)
            if om:
                tag = om.group(1)
                s = out.setdefault(tag, {}).setdefault(date, {"trades": 0, "r": 0.0})
                s["trades"] += 1
            elif cm:
                tag = cm.group(1)
                s = out.setdefault(tag, {}).setdefault(date, {"trades": 0, "r": 0.0})
                s["r"] += float(cm.group(2))
    return out


# ----------------------------------------------------------- engine journals
def summarize_engine(pattern: str) -> dict[str, dict]:
    days: dict[str, dict] = {}
    for fp in glob.glob(pattern):
        try:
            with open(fp, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get("type") != "outcome" or "opened_at" not in r:
                        continue
                    d = days.setdefault(dstr(r["opened_at"]),
                                        {"trades": 0, "r": 0.0, "pnl": 0.0,
                                         "wins": 0, "losses": 0})
                    d["trades"] += 1
                    d["r"] += float(r.get("return_r", 0.0))
                    d["pnl"] += float(r.get("pnl", 0.0))
                    if r.get("won"):
                        d["wins"] += 1
                    else:
                        d["losses"] += 1
        except OSError:
            continue
    return days


# ------------------------------------------------------------------ render
def render(days_v22, days_shadow, logs_by_tag, days_engine, weekly=False) -> None:
    alldays = sorted(set(days_v22) | set(days_shadow) |
                     {d for t in logs_by_tag.values() for d in t} | set(days_engine))

    print("=" * 96)
    print("MITEMSHUB DAILY SCOREBOARD - v22 actuals vs old-logic baselines (UTC)")
    print("=" * 96)

    if days_v22 or days_shadow:
        print(f"\n{'Date':<11}| {'Tr':>3} {'W/L':>7} {'R':>7} {'$':>9} "
              f"{'Exits T/S/Tm':>13} {'Band':>4} {'z~':>5} | {'Evals':>5} {'Take':>4} "
              f"{'MomAloneSkipped':>15}")
        print("-" * 96)
        tr_all = r_all = 0.0
        mom_saved = 0
        for d in alldays:
            v = days_v22.get(d, {})
            sh = days_shadow.get(d, {})
            tr = v.get("trades", 0)
            r = v.get("r", 0.0)
            tr_all += tr
            r_all += r
            mom_saved += sh.get("mom_alone", 0)
            ex = v.get("reasons", {})
            exits = f"{ex.get('TARGET',0)}/{ex.get('STOP',0)}/{ex.get('TIME',0)}"
            wl = f"{v.get('wins',0)}/{v.get('losses',0)}"
            band = f"{v.get('band',0)}/{tr}" if tr else "-"
            z = v.get("avg_z", 0.0)
            zs = f"{z:.2f}" if v.get("avg_z") else "-"
            print(f"{d:<11}| {tr:>3} {wl:>7} "
                  f"{r:>+7.2f} {money(v.get('pnl',0.0)):>9} {exits:>13} "
                  f"{band:>4} {zs:>5} | "
                  f"{sh.get('evals',0):>5} {sh.get('take',0):>4} {sh.get('mom_alone',0):>15}")
        print("-" * 96)
        print(f"{'TOTAL':<11}| {tr_all:>3} {'':>7} {r_all:>+7.2f} | "
              f"chase-entries avoided (old-logic would-be): {mom_saved}")

    if logs_by_tag:
        print("\n--- Parallel-chart shadow (MT5 Experts logs, per build) ---")
        for tag, dd in sorted(logs_by_tag.items()):
            tot_t = sum(v["trades"] for v in dd.values())
            tot_r = sum(v["r"] for v in dd.values())
            print(f"  [{tag:<6}] trades {tot_t:>3} | R {tot_r:>+7.2f}")
            for d in sorted(dd):
                print(f"      {d}  trades {dd[d]['trades']:>3}  R {dd[d]['r']:>+7.2f}")

    if days_engine:
        print("\n--- Python-engine journal baseline (old logic, historical) ---")
        tot_t = tot_r = tot_p = 0.0
        for d in sorted(days_engine):
            e = days_engine[d]
            tot_t += e["trades"]
            tot_r += e["r"]
            tot_p += e["pnl"]
            print(f"  {d}  trades {e['trades']:>3} ({e['wins']}W/{e['losses']}L)  "
                  f"R {e['r']:>+6.2f}  {money(e['pnl'])}")
        print(f"  TOTAL  trades {tot_t:.0f}  R {tot_r:>+7.2f}  {money(tot_p)}")

    if not alldays:
        print("\nNo data found. Point me at sources:")
        print("  --telem <telemetry.jsonl>   --logs <MT5 logs dir>   --engine-glob <pattern>")
        return

    if weekly:
        print("\n--- WEEKLY VIEW ---")
        wv22 = fold_weeks(days_v22)
        for w, v in sorted(wv22.items()):
            print(f"  v22         {w}: {v['trades']:>3} trades ({v['wins']}/{v['losses']}) "
                  f"R {v['r']:>+7.2f} {money(v['pnl'])}")
        weng = fold_weeks(days_engine)
        for w, v in sorted(weng.items()):
            print(f"  engine-old  {w}: {v['trades']:>3} trades ({v['wins']}/{v['losses']}) "
                  f"R {v['r']:>+7.2f} {money(v['pnl'])}")
        for tag, td in logs_by_tag.items():
            wt = fold_weeks({d: {"trades": v["trades"], "wins": 0, "losses": 0,
                                 "r": v["r"], "pnl": 0.0} for d, v in td.items()})
            for w, v in sorted(wt.items()):
                print(f"  shadow[{tag:<6}] {w}: {v['trades']:>3} trades           "
                      f"R {v['r']:>+7.2f}")

    # Promotion verdict needs v22 telemetry days; baseline prefers a true
    # old-build shadow ([v21.1]) then falls back to the engine journal.
    baseline_r = None
    if "v21.1" in logs_by_tag:
        baseline_r = sum(v["r"] for v in logs_by_tag["v21.1"].values())
    elif days_engine:
        baseline_r = sum(v["r"] for v in days_engine.values())
    promotion_verdict(days_v22, baseline_r)


# ---------------------------------------------------------------- selftest
def selftest() -> tuple[dict, dict, dict, dict]:
    base = 1787000000  # arbitrary recent-era epoch (seconds)
    H = 3600
    ev = []
    # Day 1: band win, ATR loss, one demoted chase, misc skips
    ev += [
        {"epoch": base, "type": "sig", "action": "TAKE", "dir": 1, "reason": "-",
         "legs": "BF+", "z": -2.31, "exp": 1.41},
        {"epoch": base, "type": "open", "ticket": 101, "dir": 1, "band": True, "z": -2.31},
        {"epoch": base + 2 * H, "type": "close", "ticket": 101, "reason": "TARGET",
         "r": 6.4, "pnl": 3.10},
        {"epoch": base + 3 * H, "type": "sig", "action": "SKIP", "dir": 0,
         "reason": "mom-demoted-lone-candle", "legs": "MOM-", "z": 1.2, "exp": 1.1},
        {"epoch": base + 4 * H, "type": "sig", "action": "TAKE", "dir": -1, "reason": "-",
         "legs": "PB-", "z": 0.4, "exp": 0.8},
        {"epoch": base + 4 * H, "type": "open", "ticket": 102, "dir": -1, "band": False,
         "z": 0.4},
        {"epoch": base + 7 * H, "type": "close", "ticket": 102, "reason": "STOP",
         "r": -1.0, "pnl": -0.52},
    ]
    # Day 2: time exit + more skipped chases
    ev += [
        {"epoch": base + 24 * H, "type": "sig", "action": "SKIP", "dir": 0,
         "reason": "score B2/S0 < min 3", "legs": "MOM+", "z": -0.9, "exp": 0.95},
        {"epoch": base + 25 * H, "type": "sig", "action": "TAKE", "dir": -1, "reason": "-",
         "legs": "MR-", "z": 2.05, "exp": 1.30},
        {"epoch": base + 25 * H, "type": "open", "ticket": 103, "dir": -1, "band": True,
         "z": 2.05},
        {"epoch": base + 28 * H, "type": "close", "ticket": 103, "reason": "TIME",
         "r": 0.12, "pnl": 0.06},
    ]
    return summarize_v22(ev), shadow_from_sigs(ev), {}, {}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--telem", help="v22 telemetry JSONL path")
    ap.add_argument("--logs", help="MT5 terminal logs directory (recursive)")
    ap.add_argument("--engine-glob", dest="engine_glob", help='e.g. "journals/forward_demo_*.jsonl"')
    ap.add_argument("--json", dest="jsonp", help="also write summary to this JSON file")
    ap.add_argument("--selftest", action="store_true", help="run pipeline on synthetic events")
    ap.add_argument("--weekly", action="store_true",
                    help="also show ISO-week rollup + promotion verdict")
    a = ap.parse_args(argv)

    if a.selftest:
        dv, dsh, _, _ = selftest()
        print("[selftest] synthetic events -> expect 3 trades, R +5.52, "
              "2 mom-alone skips\n")
        render(dv, dsh, {}, {})
        return 0

    days_v22, days_shadow = {}, {}
    if a.telem:
        ev = load_telem(a.telem)
        print(f"[telem] {len(ev)} events from {a.telem}")
        days_v22 = summarize_v22(ev)
        days_shadow = shadow_from_sigs(ev)

    logs_by_tag = parse_expert_logs(a.logs) if a.logs else {}
    if a.logs:
        n = sum(len(t) for t in logs_by_tag.values())
        print(f"[logs] {n} tag-days parsed from {a.logs}")

    days_engine = summarize_engine(a.engine_glob) if a.engine_glob else {}
    if a.engine_glob:
        print(f"[engine] {sum(e['trades'] for e in days_engine.values())} outcomes from {a.engine_glob}")

    render(days_v22, days_shadow, logs_by_tag, days_engine, weekly=a.weekly)

    if a.jsonp:
        payload = {"v22": days_v22, "shadow_sigs": days_shadow,
                   "expert_logs": logs_by_tag, "engine": days_engine}
        Path(a.jsonp).write_text(json.dumps(payload, indent=1), encoding="utf-8")
        print(f"\n[wrote] {a.jsonp}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
