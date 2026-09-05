"""One-command morning status for the V75 paper A/B (read-only, no MT5 needed).

    python scripts/morning_status.py
    python scripts/morning_status.py --days 1 --strict

Answers, in order:
  [1] ARM HEALTH   - per paper-arm terminal: terminal-process count, the EA's
                     last telemetry write age, ledger virtual equity + integrity.
  [2] NIGHT GAPS   - per-terminal journal audit for the last N days (default 3):
                     "connection lost" -> next "authorized" spans, including
                     cross-midnight pairs and still-open gaps.
  [3] LEDGERS      - closed trades per arm, total/mean R, virtual equity, and
                     go-live gate progress (X/30 closed trades per arm, with
                     projected days-to-30 at the observed rate).

The pre-registered gate: >= 30 closed arm-A trades with POSITIVE expectancy
+ tick reconciliation PASS (self-arms at 7d of ledger) + watchdog CERTIFIED.

Exit code 0 always (a status report, not a check); --strict exits 1 when any
arm looks unhealthy (telemetry stale > 2h, no telemetry, ledger problems).

Wire format (EA v26.35 writer, MitemshubAI.mq5 PaperLog):
  OPEN,epoch,ticket,dir,entry,sl,tp,vol,eff_risk,orig_risk,max_hold,tag   (12 fields)
  CLOSE,epoch,ticket,reason,exit,r,pnl,veq                                 (8 fields)
  EQ,veq
Epochs are SECONDS (TimeCurrent).
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

LEDGER = "MitemshubAI_paper_Volatility_75_Index.csv"
TELEM = "MitemshubAI_v23_telemetry_Volatility_75_Index.jsonl"
TERM_ROOT = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal")
MAGICS = {"A_tp18": 7788075, "B_tp24": 7788100}
MIN_TRADES = 30
STALE_TELEM_S = 2 * 3600  # telemetry older than this counts as stale
WINDOW_DAYS = 3           # default journal audit window

C = {"g": "\033[92m", "y": "\033[93m", "r": "\033[91m", "b": "\033[94m", "0": "\033[0m", "B": "\033[1m"}


def paint(s: str, *keys: str) -> str:
    if not sys.stdout.isatty():
        return s
    return "".join(C[k] for k in keys) + s + C["0"]


def human_age(seconds: float) -> str:
    s = int(seconds)
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s // 60}m"
    if s < 172800:
        return f"{s / 3600:.1f}h"
    return f"{s / 86400:.1f}d"


def parse_journal(path: str, day: datetime) -> list[tuple[datetime, str]]:
    """Parse one MT5 terminal journal (UTF-16LE, `HH:MM:SS.mmm\tMsg` lines with
    an optional 2-char severity prefix) -> [(full datetime, message)]."""
    out = []
    try:
        with open(path, encoding="utf-16", errors="replace") as f:
            for line in f:
                m = re.match(r"^(?:[A-Z]{2}\t\d\t)?(\d{2}):(\d{2}):(\d{2})\.\d+\t(.*)$", line.rstrip("\r\n"))
                if not m:
                    continue
                hh, mm, ss, msg = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4).strip()
                ts = day.replace(hour=hh, minute=mm, second=ss, microsecond=0)
                out.append((ts, msg))
    except OSError:
        pass
    return out


def journal_gaps(logs_dir: str, window_start: datetime, now_local: datetime) -> list[dict]:
    """Connection gaps across the whole window as ONE merged stream, so a
    'lost' just before midnight pairs with its 'authorized' after midnight.
    'connection lost'/'no connection' opens a gap; 'authorized' closes it."""
    entries: list[tuple[datetime, str]] = []
    day = window_start
    while day <= now_local:
        entries.extend(parse_journal(os.path.join(logs_dir, f"{day:%Y%m%d}.log"), day))
        day += timedelta(days=1)

    gaps = []
    lost_at = None
    for ts, msg in entries:
        low = msg.lower()
        # journal wording: "connection to <server> lost", "no connection", or
        # "connection to <server> lost because there is no connection" - the
        # invariant is the pair (lost|no connection) ... "authorized"
        opens = ("lost" in low and "connection" in low) or "no connection" in low
        if opens and lost_at is None:
            lost_at = ts
        elif "authorized" in low and lost_at is not None:
            gaps.append({"lost": lost_at, "back": ts, "open": False})
            lost_at = None
    if lost_at is not None:
        gaps.append({"lost": lost_at, "back": None, "open": True})
    return gaps


def terminal_inventory() -> list[dict]:
    """All terminal data folders with a V75 chart profile carrying an arm magic."""
    inv = []
    now_epoch = datetime.now().timestamp()
    for td in sorted(glob.glob(os.path.join(TERM_ROOT, "*"))):
        if not os.path.isdir(td):
            continue
        magic = None
        for chr_f in glob.glob(os.path.join(td, "MQL5", "Profiles", "Charts", "*", "*.chr")):
            try:
                txt = open(chr_f, encoding="utf-16", errors="replace").read()
            except OSError:
                continue
            if "Volatility 75" in txt:
                m = re.search(r"^InpMagic=(7788075|7788100)$", txt, re.M)
                if m:
                    magic = m.group(1)
                    break
        if magic is None:
            continue
        name = next((k for k, v in MAGICS.items() if str(v) == magic), f"?{magic}")
        files_dir = os.path.join(td, "MQL5", "Files")
        telem_path = os.path.join(files_dir, TELEM)
        telem_age = (now_epoch - os.path.getmtime(telem_path)) if os.path.exists(telem_path) else None
        inv.append({"name": name, "magic": magic, "dir": td, "files_dir": files_dir,
                    "telem_age": telem_age, "ledger_path": os.path.join(files_dir, LEDGER)})
    return inv


def terminals_running() -> int:
    """Count of running terminal64.exe via tasklist (no psutil dependency)."""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/FO", "CSV"],
                             capture_output=True, text=True, timeout=15).stdout
        return sum(1 for line in out.splitlines() if line.lower().startswith('"terminal64.exe"'))
    except (OSError, subprocess.SubprocessError):
        return -1


def parse_ledger(path: str) -> dict:
    """Closed trades + veq + integrity from the paper ledger (same format the
    A/B adjudicator parses; kept local so this tool stays standalone)."""
    res: dict = {"closed": [], "veq_last": None, "problems": []}
    open_rows: dict[str, str] = {}
    try:
        with open(path) as f:
            for line in f:
                parts = line.strip().split(",")
                if not parts:
                    continue
                if parts[0] == "OPEN" and len(parts) >= 12:
                    open_rows[parts[2]] = parts[1]
                elif parts[0] == "CLOSE" and len(parts) >= 8:
                    open_rows.pop(parts[2], None)
                    res["closed"].append({"epoch": int(parts[1]), "reason": parts[3],
                                          "r": float(parts[5]), "pnl": float(parts[6]),
                                          "veq": float(parts[7])})
                elif parts[0] == "EQ" and len(parts) >= 2:
                    res["veq_last"] = float(parts[1])
    except OSError as e:
        res["problems"].append(f"unreadable: {e}")
        return res
    except (ValueError, IndexError) as e:
        res["problems"].append(f"corrupt row: {e}")
        return res
    if len(open_rows) > 1:
        res["problems"].append(f"{len(open_rows)} OPEN rows without CLOSE (1 live + {len(open_rows) - 1} dangling)")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description="Morning status for the V75 paper A/B")
    ap.add_argument("--days", type=int, default=WINDOW_DAYS, help="journal audit window (days)")
    ap.add_argument("--strict", action="store_true", help="exit 1 when any arm looks unhealthy")
    args = ap.parse_args()

    now_local = datetime.now()
    now_epoch = now_local.timestamp()
    n_running = terminals_running()
    inv = terminal_inventory()
    window_start = (now_local - timedelta(days=args.days)).replace(hour=0, minute=0, second=0, microsecond=0)
    unhealthy = False

    print(paint(f"=== MITEMSHUB MORNING STATUS - {now_local:%Y-%m-%d %H:%M} ===", "B"))

    print(paint("[1] ARM HEALTH", "b"))
    if not inv:
        print("  no terminal data folder with a V75 chart + arm magic found")
        unhealthy = True
    else:
        print(f"  terminal64.exe processes running: {n_running} (arms need >= {len(inv)})")
        if 0 <= n_running < len(inv):
            print(paint("    ! fewer terminals running than arms configured", "y"))
    for t in inv:
        age = t["telem_age"]
        if age is None:
            telem_s = paint("no telemetry file", "r")
            unhealthy = True
        else:
            stale = age > STALE_TELEM_S
            telem_s = paint(f"telemetry last write {human_age(age)} ago" + (" STALE" if stale else ""),
                            "y" if stale else "g")
            if stale:
                unhealthy = True
        if os.path.exists(t["ledger_path"]):
            led = parse_ledger(t["ledger_path"])
            veq = led["veq_last"]
            veq_s = f"${veq:,.2f}" if veq is not None else "?"
            state = f"veq {veq_s}, {len(led['closed'])} closed"
            led_s = paint(state, "g" if not led["problems"] else "r")
            if led["problems"]:
                unhealthy = True
                state += "  " + "; ".join(led["problems"])
            print(f"  {t['name']} (magic {t['magic']}): {telem_s} | {led_s}")
        else:
            print(f"  {t['name']} (magic {t['magic']}): {telem_s} | "
                  + paint("no paper ledger yet", "y"))

    print(paint(f"[2] NIGHT GAPS (last {args.days}d, terminal journals)", "b"))
    BLIP_S = 60  # reconnect flaps shorter than this are MT5 server-hopping noise
    for t in inv:
        gaps = journal_gaps(os.path.join(t["dir"], "logs"), window_start, now_local)
        if not gaps:
            print(f"  {t['name']}: no connection gaps in window")
            continue
        major = [g for g in gaps
                 if g["back"] is None or (g["back"] - g["lost"]).total_seconds() >= BLIP_S]
        n_blips = len(gaps) - len(major)
        blip_s = f"  (+{n_blips} sub-{BLIP_S}s reconnect flaps, MT5 access-point hopping)" if n_blips else ""
        if not major:
            print(f"  {t['name']}: no significant gaps{blip_s}")
            continue
        print(f"  {t['name']}:")
        for g in major:
            back_s = "(still open)" if g["back"] is None else f"{g['back']:%H:%M:%S}"
            if g["back"] is None:
                span = f"still open, {human_age((now_local - g['lost']).total_seconds())} so far"
            else:
                span = human_age((g["back"] - g["lost"]).total_seconds())
            print(f"    {g['lost']:%m-%d %H:%M:%S} -> {back_s}  [{span}]{blip_s if g is major[-1] else ''}")

    print(paint("[3] LEDGERS + GO-LIVE GATE", "b"))
    for t in inv:
        if not os.path.exists(t["ledger_path"]):
            print(f"  {t['name']}: 0/{MIN_TRADES} closed trades - gate clock starts at first fill")
            continue
        closed = parse_ledger(t["ledger_path"])["closed"]
        if not closed:
            print(f"  {t['name']}: 0/{MIN_TRADES} closed trades - gate clock starts at first fill")
            continue
        n = len(closed)
        total_r = sum(c["r"] for c in closed)
        mean_r = total_r / n
        days = max((closed[-1]["epoch"] - closed[0]["epoch"]) / 86400, 1 / 24)
        rate = n / days
        if n < MIN_TRADES and rate > 0:
            eta = (MIN_TRADES - n) / rate
            tail = f"~{eta:.0f}d to {MIN_TRADES} at {rate:.1f}/day"
        else:
            tail = f"{rate:.1f}/day - data gate MET"
        verdict = "POSITIVE" if mean_r > 0 else paint("NOT positive", "y")
        reasons = {c["reason"]: sum(1 for x in closed if x["reason"] == c["reason"]) for c in closed}
        print(f"  {t['name']}: {n}/{MIN_TRADES} closed | totalR {total_r:+.2f} | "
              f"meanR {mean_r:+.3f} ({verdict}) | {tail}")
        print("      exits: " + ", ".join(f"{k}:{v}" for k, v in sorted(reasons.items())))

    print()
    print(paint("Gate reminder (pre-registered):", "b"))
    print(f"  >= {MIN_TRADES} closed arm-A trades with POSITIVE expectancy")
    print("  + tick reconciliation PASS (self-arms at 7d of ledger)")
    print("  + watchdog CERTIFIED  ->  live authorized at the pre-registered size")

    if args.strict and unhealthy:
        print(paint("\nSTRICT: unhealthy signals present (see [1])", "r"))
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
