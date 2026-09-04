"""Paper weekly report — one command, three sections (pre-registered layout).

    python scripts/paper_weekly.py

  [1] LEDGER EXPECTANCY — per terminal: closed paper trades, total/mean R,
      WR, $pnl, virtual-equity drawdown, reasons split. Reference line is the
      210-day walk-forward tp18 expectancy (+0.105 R/trade over ~500 trades);
      with n < 30 the section is explicitly exploratory, no verdict.
  [2] WATCHDOG VERDICT — reuses demo_watchdog.audit()/paper_audit() verbatim
      (same checks, same pass/fail lists), prints verdict + any FAILs.
  [3] PRESET DRIFT — three layers, newest first:
      (a) CHART-ATTACHED inputs (per terminal .chr, what the EA would run
          with after a reload) vs the deployed preset matched by magic.
          Catches the "preset updated, EA never reloaded" failure mode.
      (b) repo preset vs deployed Common\\Presets copy (key=value diff).
      (c) EA binary freshness: terminal .ex5 mtime vs repo source mtime.
      Also flags: banner version vs repo APP_VERSION, duplicate magics across
      charts, and any V75 chart with InpLiveExecution=true (landmine).

Writes artifacts/v75_replay/weekly_report_YYYYMMDD.json. Read-only: it never
modifies terminal or repo state.
"""
from __future__ import annotations

import glob
import json
import os
import re
import statistics as st
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from demo_watchdog import audit, paper_audit  # noqa: E402  (same checks as the watchdog)

DATA = os.path.join(HERE, "..", "artifacts", "v75_replay")
APPDATA = os.environ.get("APPDATA", "")
TERM_ROOT = os.path.join(APPDATA, "MetaQuotes", "Terminal")
COMMON_PRESETS = os.path.join(TERM_ROOT, "Common", "MQL5", "Presets")
REPO_PRESETS = os.path.join(HERE, "..", "mql5", "MITEMSHUB_AI")
EA_SOURCE = os.path.join(HERE, "..", "mql5", "MITEMSHUB_AI", "MitemshubAI.mq5")
LEDGER_GLOB = "MitemshubAI_paper_*.csv"
MAGIC_TO_PRESET = {7788075: "MitemshubAI_VOL75_FINAL.set", 7788100: "MitemshubAI_VOL75_TP24.set"}
REF_MEAN_R = 0.105          # tp18, 210-day walk-forward (~500 trades)
REF_SOURCE = "walkforward_210d.json tp18"
MIN_N_VERDICT = 30


# ------------------------------------------------------------- presets ----
def read_preset(path) -> dict:
    vals = {}
    if not os.path.exists(path):
        return vals
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.match(r"^(Inp\w+)=(.*)$", line.strip())
            if m:
                vals[m.group(1)] = m.group(2)
    return vals


def diff_keys(a: dict, b: dict, keys) -> list:
    out = []
    for k in keys:
        if k in a and k in b and a[k] != b[k]:
            out.append(f"{k}: {b[k]!r} -> {a[k]!r}")
    return out


# ---------------------------------------------------------- chart .chr ----
def parse_chr(path) -> dict:
    """UTF-16LE key=value chart file; returns symbol, expert path, inputs."""
    try:
        txt = open(path, encoding="utf-16", errors="replace").read()
    except OSError:
        return {}
    out, in_expert = {"path": path}, False
    inputs = {}
    for line in txt.splitlines():
        line = line.strip()
        if line == "<expert>":
            in_expert = True
        elif line == "</expert>":
            in_expert = False
        elif in_expert:
            m = re.match(r"^(Inp\w+)=(.*)$", line)
            if m:
                inputs[m.group(1)] = m.group(2)
            elif re.match(r"^path=(.+)$", line):
                out["expert"] = m2.group(1) if (m2 := re.match(r"^path=(.+)$", line)) else None
        if line.startswith("symbol="):
            out["symbol"] = line[7:]
        m = re.match(r"^descr==== MITEMSHUB AI v([\d.]+)", line)
        if m:
            out["banner_version"] = m.group(1)
    out["inputs"] = inputs
    return out


def scan_charts(term_dir) -> list:
    charts = []
    for pat in ("MQL5/Profiles/Charts/*/*.chr",):
        for f in glob.glob(os.path.join(term_dir, pat)):
            c = parse_chr(f)
            if "Mitemshub" in (c.get("expert") or ""):
                charts.append(c)
    return charts


# ------------------------------------------------------------- ledger -----
def ledger_expectancy(path) -> dict:
    opens, trades, curve = {}, [], []
    with open(path) as f:
        for line in f:
            p = line.strip().split(",")
            if not p:
                continue
            if p[0] == "OPEN":
                opens[p[2]] = int(p[1])
            elif p[0] == "CLOSE":
                o = opens.pop(p[2], None)
                trades.append(dict(epoch=int(p[1]), r=float(p[5]), pnl=float(p[6]),
                                   reason=p[3], open_epoch=o))
            elif p[0] == "EQ":
                curve.append(float(p[1]))
    if not trades:
        return {"closed": 0}
    rs = [t["r"] for t in trades]
    days = (trades[-1]["epoch"] - trades[0]["epoch"]) / 86400
    peak = trough = curve[0] if curve else 0.0
    dd = 0.0
    for v in curve:
        peak = max(peak, v)
        dd = max(dd, peak - v)
    streak = worst = 0
    for r in rs:
        streak = streak + 1 if r <= 0 else 0
        worst = max(worst, streak)
    return {
        "closed": len(rs), "days": round(days, 2),
        "total_r": round(sum(rs), 2), "mean_r": round(st.mean(rs), 3),
        "wr": round(100 * sum(1 for r in rs if r > 0) / len(rs), 1),
        "pnl": round(sum(t["pnl"] for t in trades), 2),
        "veq_dd": round(dd, 2), "worst_streak": worst,
        "trades_per_day": round(len(rs) / days, 2) if days > 0 else None,
        "reasons": {k: v for k, v in sorted((x, [t["reason"] for t in trades].count(x))
                                            for x in {t["reason"] for t in trades})},
        "vs_ref": round(st.mean(rs) - REF_MEAN_R, 3),
    }


# ------------------------------------------------------------- main -------
def main() -> None:
    now = datetime.now()
    report = {"generated": now.isoformat(timespec="seconds"),
              "ref_expectancy": {"mean_r": REF_MEAN_R, "source": REF_SOURCE},
              "sections": {}}

    print(f"=== PAPER WEEKLY REPORT {now:%Y-%m-%d %H:%M} ===")

    # ---- [1] ledger expectancy across terminals --------------------------
    print("\n[1] LEDGER EXPECTANCY")
    ledgers = []
    for term_dir in sorted(glob.glob(os.path.join(TERM_ROOT, "*"))):
        fdir = os.path.join(term_dir, "MQL5", "Files")
        if os.path.isdir(fdir):
            for f in glob.glob(os.path.join(fdir, LEDGER_GLOB)):
                ledgers.append((term_dir, f))
    sec1 = {}
    if not ledgers:
        print("  no paper ledgers exist yet — the EA has not paper-traded "
              "(reload with VOL75_FINAL.set; arm B in a second terminal)")
    for term_dir, f in ledgers:
        exp = ledger_expectancy(f)
        arm = "?"
        for c in scan_charts(term_dir):
            mg = (c["inputs"].get("InpMagic") or "")
            if mg.isdigit():
                arm = MAGIC_TO_PRESET.get(int(mg), f"magic {mg}").replace("MitemshubAI_VOL75_", "").replace(".set", "")
        name = f"{os.path.basename(term_dir)[:12]}… [{arm}]"
        sec1[name] = exp
        if exp.get("closed"):
            print(f"  {name}: n={exp['closed']} over {exp['days']}d | {exp['total_r']:+.2f}R "
                  f"(mean {exp['mean_r']:+.3f}R/trade, ref {REF_MEAN_R:+.3f} → {exp['vs_ref']:+.3f}) | "
                  f"WR {exp['wr']}% ${exp['pnl']:+.2f} vDD ${exp['veq_dd']:.2f} worst-streak {exp['worst_streak']}")
            if exp["closed"] < MIN_N_VERDICT:
                print(f"    n<{MIN_N_VERDICT}: exploratory only — no performance verdict")
        else:
            print(f"  {name}: ledger exists, no closed trades yet")
    report["sections"]["expectancy"] = sec1

    # ---- [2] watchdog ----------------------------------------------------
    print("\n[2] WATCHDOG VERDICT")
    try:
        passes, fails, warns = audit()
        pp, pf, pw = paper_audit()
        passes += pp; fails += pf; warns += pw
        verdict = "CERTIFIED" if not fails else "VIOLATIONS PRESENT"
        print(f"  {verdict} ({len(passes)} pass / {len(fails)} fail / {len(warns)} warn)")
        for x in fails[:5]:
            print(f"    FAIL  {x}")
        sec2 = {"verdict": verdict, "pass": len(passes), "fail": len(fails),
                "warn": len(warns), "fails": fails[:10]}
    except Exception as e:  # mt5 unavailable etc — report, don't crash
        print(f"  unavailable: {e}")
        sec2 = {"error": str(e)}
    report["sections"]["watchdog"] = sec2

    # ---- [3] preset drift -------------------------------------------------
    print("\n[3] PRESET DRIFT")
    sec3 = {"charts": [], "repo_vs_deployed": [], "binary": []}
    repo_v = ""
    src = open(EA_SOURCE, encoding="utf-8", errors="replace").read()
    m = re.search(r'#define\s+APP_VERSION\s+"([\d.]+)"', src)
    if m:
        repo_v = m.group(1)
    src_mtime = os.path.getmtime(EA_SOURCE)

    drift_count = 0
    seen_magics = {}
    for term_dir in sorted(glob.glob(os.path.join(TERM_ROOT, "*"))):
        charts = scan_charts(term_dir)
        tname = os.path.basename(term_dir)[:12]
        for c in charts:
            if "75" not in (c.get("symbol") or ""):
                continue
            mg = (c["inputs"].get("InpMagic") or "").strip()
            row = {"terminal": tname, "chart": os.path.basename(c["path"]),
                   "symbol": c.get("symbol"), "magic": mg,
                   "banner_version": c.get("banner_version"), "drift": []}
            if mg in seen_magics and seen_magics[mg] != (tname, c["path"]):
                row["drift"].append(f"DUPLICATE magic {mg} (also {seen_magics[mg][0]})")
            seen_magics[mg] = (tname, c["path"])
            if c.get("banner_version") and repo_v and c["banner_version"] != repo_v:
                row["drift"].append(f"chart banner v{c['banner_version']} vs repo v{repo_v} "
                                    "(EA attached/reloaded at older version)")
            if c["inputs"].get("InpLiveExecution", "").lower() == "true":
                row["drift"].append("LIVE EXECUTION on a V75 chart — intended?")
            preset = MAGIC_TO_PRESET.get(int(mg)) if mg.isdigit() else None
            if preset:
                deployed = read_preset(os.path.join(COMMON_PRESETS, preset))
                repo = read_preset(os.path.join(REPO_PRESETS, preset))
                chk = diff_keys(repo, deployed, sorted(set(repo) & set(deployed)))
                if chk:
                    sec3["repo_vs_deployed"] += [f"{preset}: {x}" for x in chk]
                    row["drift"].append("deployed preset differs from repo (see repo_vs_deployed)")
                d = diff_keys(deployed, c["inputs"], sorted(set(deployed) & set(c["inputs"])))
                if d:
                    row["drift"] += [f"chart-vs-preset {x}" for x in d]
            elif mg:
                row["drift"].append(f"magic {mg} maps to no known preset")
            if row["drift"]:
                drift_count += len(row["drift"])
                print(f"  DRIFT {tname}/{row['chart']} ({row['symbol']}, magic {mg or '?'}):")
                for d in row["drift"]:
                    print(f"    - {d}")
            else:
                print(f"  ok    {tname}/{row['chart']} (magic {mg}) matches deployed preset")
            sec3["charts"].append(row)

    # binary freshness
    for term_dir in sorted(glob.glob(os.path.join(TERM_ROOT, "*"))):
        ex5 = os.path.join(term_dir, "MQL5", "Experts", "MITEMSHUB_AI", "MitemshubAI.ex5")
        if os.path.exists(ex5):
            age = (datetime.fromtimestamp(src_mtime) - datetime.fromtimestamp(os.path.getmtime(ex5)))
            if age.total_seconds() > 60:
                sec3["binary"].append(f"{os.path.basename(term_dir)[:12]}: ex5 older than repo source by {age}")
    for b in sec3["binary"]:
        print(f"  BINARY {b}")

    if drift_count == 0 and not sec3["binary"] and not sec3["repo_vs_deployed"]:
        print("  no drift detected")
    report["sections"]["drift"] = sec3

    # ---- actions ----------------------------------------------------------
    print("\nNEXT ACTIONS")
    acts = []
    if not ledgers:
        acts.append("reload the EA on the V75 M15 chart with VOL75_FINAL.set "
                    "(arm B: VOL75_TP24.set in a second terminal)")
    for row in sec3["charts"]:
        if any("chart-vs-preset" in d or "banner" in d for d in row["drift"]):
            acts.append(f"reload EA on {row['terminal']}/{row['chart']} — chart inputs are stale vs deployed preset")
        if any("LIVE EXECUTION" in d for d in row["drift"]):
            acts.append(f"inspect {row['terminal']}/{row['chart']}: live-execution V75 chart")
    for name, exp in sec1.items():
        if isinstance(exp, dict) and exp.get("closed", 0) >= MIN_N_VERDICT:
            acts.append(f"{name}: ≥{MIN_N_VERDICT} closed trades — run scripts/ab_adjudicate.py and "
                        "scripts/reconcile_paper_ticks.py")
    for a in acts[:6]:
        print(f"  - {a}")
    report["actions"] = acts

    out = os.path.join(DATA, f"weekly_report_{now:%Y%m%d}.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=1)
    print(f"\nartifact: {out}")


if __name__ == "__main__":
    main()
