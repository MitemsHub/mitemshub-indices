"""Tests for scripts/meta_label_trainer.py — sig/close joining, the
regime|direction lookup table, and the symbol-tagged CSV copy step that
feeds the EA's SymbolTaggedFile() lookup.

All tests run fully offline (no MT5 terminal, no real telemetry).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT / "scripts"))

import meta_label_trainer as trainer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sig_event(sym: str = "Crash 1000 Index", direction: int = 1,
               regime: str = "BULLISH", **extra) -> dict:
    """A v26.4-style telemetry 'sig' event with action=TAKE."""
    ev = {
        "type": "sig",
        "action": "TAKE",
        "sym": sym,
        "dir": direction,
        "regime": regime,
        "z": 1.5,
        "exp": 0.8,
        "sigma": 0.002,
        "sigma_base": 0.001,
        "band_geom": False,
        "score_b": 4.0,
        "score_s": 0.0,
        "legs": "PB",
    }
    ev.update(extra)
    return ev


def close_event(r: float, reason: str = "tp") -> dict:
    return {"type": "close", "r": r, "reason": reason}


def take_close_pair(sym: str = "Crash 1000 Index", direction: int = 1,
                    regime: str = "BULLISH", r: float = 1.0) -> list[dict]:
    return [sig_event(sym, direction, regime), close_event(r)]


def write_telemetry(path: Path, events: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    return path


def run_trainer(monkeypatch, telemetry: Path, out_dir: Path,
                ea_files_dir: Path | None = None, appdata: Path | None = None):
    """Invoke trainer.main() with an explicit argv, capturing nothing."""
    argv = ["meta_label_trainer.py", "--telemetry", str(telemetry),
            "--out-dir", str(out_dir)]
    if ea_files_dir is not None:
        argv += ["--ea-files-dir", str(ea_files_dir)]
    if appdata is not None:
        monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(sys, "argv", argv)
    trainer.main()


def make_trades(n: int, sym: str = "Crash 1000 Index", direction: int = 1,
                regime: str = "BULLISH", r: float = 1.0) -> list[dict]:
    """n completed sig/close pairs (deterministic)."""
    events: list[dict] = []
    for _ in range(n):
        events += take_close_pair(sym, direction, regime, r)
    return events


# ---------------------------------------------------------------------------
# join_signals
# ---------------------------------------------------------------------------

class TestJoinSignals:
    def test_pairs_take_with_next_close(self):
        events = take_close_pair(r=1.7)
        trades = trainer.join_signals(events)
        assert len(trades) == 1
        t = trades[0]
        assert t["sym"] == "Crash 1000 Index"
        assert t["dir"] == 1
        assert t["regime"] == "BULLISH"
        assert t["r"] == 1.7
        assert t["sigma_ratio" if "sigma_ratio" in t else "sigma"] is not None

    def test_skip_signals_are_ignored(self):
        skip = sig_event()
        skip["action"] = "SKIP"
        events = [skip, close_event(r=1.0)]
        assert trainer.join_signals(events) == []

    def test_close_without_open_sig_is_dropped(self):
        assert trainer.join_signals([close_event(r=2.0)]) == []

    def test_close_binds_to_most_recent_take(self):
        # EA is single-position-per-symbol: the next close after a TAKE
        # belongs to the most recent TAKE, and it resets the open slot.
        events = [
            sig_event(sym="A", regime="BULLISH"),
            sig_event(sym="B", regime="BEARISH"),   # replaces the open A
            close_event(r=0.5),
        ]
        trades = trainer.join_signals(events)
        assert len(trades) == 1
        assert trades[0]["sym"] == "B"

    def test_multiple_sequential_pairs(self):
        events = [
            *take_close_pair(sym="A", r=1.0),
            *take_close_pair(sym="B", r=-0.8),
            *take_close_pair(sym="C", r=2.2),
        ]
        trades = trainer.join_signals(events)
        assert [t["sym"] for t in trades] == ["A", "B", "C"]
        assert [t["r"] for t in trades] == [1.0, -0.8, 2.2]

    def test_missing_context_fields_become_none(self):
        events = [{"type": "sig", "action": "TAKE"}, close_event(r=0.1)]
        trades = trainer.join_signals(events)
        assert len(trades) == 1
        t = trades[0]
        for key in ("sym", "regime", "z", "sigma", "band_geom"):
            assert t[key] is None

    def test_non_take_non_sig_events_pass_through(self):
        events = [
            {"type": "reject", "reason": "x"},
            *take_close_pair(r=1.0),
            {"type": "open"},
        ]
        assert len(trainer.join_signals(events)) == 1


# ---------------------------------------------------------------------------
# build_regime_table
# ---------------------------------------------------------------------------

class TestBuildRegimeTable:
    def _join(self, events):
        return trainer.join_signals(events)

    def test_groups_by_regime_and_direction(self):
        trades = self._join([
            *make_trades(3, regime="BULLISH", direction=1, r=1.0),
            *make_trades(2, regime="BULLISH", direction=-1, r=0.5),
        ])
        table = trainer.build_regime_table(trades)
        assert set(table) == {"bullish|long", "bullish|short"}
        assert table["bullish|long"]["n"] == 3
        assert table["bullish|short"]["n"] == 2

    def test_counts_and_win_rate(self):
        trades = self._join([
            *make_trades(3, regime="RANGING", r=1.0),
            *make_trades(2, regime="RANGING", r=-1.0),
        ])
        info = trainer.build_regime_table(trades)["ranging|long"]
        assert info["n"] == 5
        assert info["win_rate"] == 0.6
        assert info["avg_r"] == pytest.approx(0.2)

    def test_negative_mean_r_gets_zero_multiplier(self):
        trades = self._join(make_trades(trainer.MIN_TRADES_PER_BUCKET + 1,
                                        regime="BEARISH", r=-0.5))
        info = trainer.build_regime_table(trades)["bearish|long"]
        assert info["multiplier"] == 0.0
        assert info["note"] == "no_edge_or_thin_data"

    def test_thin_data_gets_zero_multiplier_even_with_edge(self):
        trades = self._join(make_trades(trainer.MIN_TRADES_PER_BUCKET - 1,
                                        regime="BULLISH", r=2.0))
        info = trainer.build_regime_table(trades)["bullish|long"]
        assert info["multiplier"] == 0.0
        assert info["note"] == "no_edge_or_thin_data"

    def test_positive_edge_scales_relative_to_baseline(self):
        n = trainer.MIN_TRADES_PER_BUCKET + 2
        trades = self._join([
            # good context: mean R 2.0
            *make_trades(n, regime="BULLISH", r=2.0),
            # mediocre context: mean R 1.0 (drags the baseline down)
            *make_trades(n, regime="BEARISH", r=1.0),
        ])
        table = trainer.build_regime_table(trades)
        bull = table["bullish|long"]
        base_mean = (n * 2.0 + n * 1.0) / (2 * n)
        assert bull["note"] == "relative_expectancy"
        # 2.0 / 1.5 = 1.333 — below the 1.5 hard cap, so unclipped
        assert bull["multiplier"] == pytest.approx(2.0 / base_mean, abs=1e-3)

    def test_multiplier_hard_capped_at_1_5(self):
        n = trainer.MIN_TRADES_PER_BUCKET + 2
        trades = self._join([
            *make_trades(n, regime="BULLISH", r=10.0),
            *make_trades(n, regime="BEARISH", r=0.1),
        ])
        assert trainer.build_regime_table(trades)["bullish|long"]["multiplier"] == 1.5

    def test_dir_zero_or_missing_maps_to_short(self):
        trades = self._join([
            *make_trades(2, direction=0, r=0.3),
            *make_trades(2, direction=-1, r=0.3),
        ])
        table = trainer.build_regime_table(trades)
        assert table["bullish|short"]["n"] == 4

    def test_missing_r_treated_as_zero(self):
        trades = self._join(make_trades(2, r=0.3))
        for t in trades:
            t["r"] = None
        table = trainer.build_regime_table(trades)
        assert table["bullish|long"]["avg_r"] == 0.0
        assert table["bullish|long"]["multiplier"] == 0.0

    def test_regime_names_lowercased(self):
        trades = self._join(make_trades(2, regime="HIGH_VOL"))
        assert "high_vol|long" in trainer.build_regime_table(trades)


# ---------------------------------------------------------------------------
# Symbol-tagged copy step (end-to-end through main())
# ---------------------------------------------------------------------------

class TestSymbolTaggedCopies:
    def test_writes_base_and_symbol_tagged_csv(self, tmp_path, monkeypatch):
        telemetry = write_telemetry(tmp_path / "telem.jsonl",
                                    make_trades(4, sym="Crash 1000 Index"))
        out_dir = tmp_path / "out"
        ea_dir = tmp_path / "eafiles"
        run_trainer(monkeypatch, telemetry, out_dir, ea_files_dir=ea_dir)

        base = out_dir / "meta_label_regime_table.csv"
        tagged = out_dir / "meta_label_regime_table_Crash_1000_Index.csv"
        ea_copy = ea_dir / "meta_label_regime_table_Crash_1000_Index.csv"

        # spaces -> underscores, matching SymbolTaggedFile()'s tag
        assert base.exists()
        assert tagged.exists()
        assert ea_copy.exists()

        header = "regime,direction,n,win_rate,avg_r,multiplier,note"
        body = base.read_text(encoding="utf-8")
        assert body.splitlines()[0] == header
        # every copy carries identical body (same table for all symbols)
        assert tagged.read_text(encoding="utf-8") == body
        assert ea_copy.read_text(encoding="utf-8") == body

    def test_one_tagged_copy_per_distinct_symbol(self, tmp_path, monkeypatch):
        events = [
            *make_trades(3, sym="Crash 1000 Index", r=1.0),
            *make_trades(3, sym="Boom 1000 Index", r=-0.5),
        ]
        telemetry = write_telemetry(tmp_path / "telem.jsonl", events)
        out_dir = tmp_path / "out"
        ea_dir = tmp_path / "eafiles"
        run_trainer(monkeypatch, telemetry, out_dir, ea_files_dir=ea_dir)

        for tag in ("Crash_1000_Index", "Boom_1000_Index"):
            assert (out_dir / f"meta_label_regime_table_{tag}.csv").exists()
            assert (ea_dir / f"meta_label_regime_table_{tag}.csv").exists()

    def test_accepts_symbol_key_fallback(self, tmp_path, monkeypatch):
        # calibration-outcomes-style journals use "symbol" instead of "sym"
        events = make_trades(3, r=0.8)
        for ev in events:
            if ev["type"] == "sig":
                ev["symbol"] = ev.pop("sym")
        telemetry = write_telemetry(tmp_path / "telem.jsonl", events)
        out_dir = tmp_path / "out"
        run_trainer(monkeypatch, telemetry, out_dir)

        tagged = out_dir / "meta_label_regime_table_Crash_1000_Index.csv"
        assert tagged.exists(), "symbol-key fallback should still tag correctly"
        assert not (out_dir / "meta_label_regime_table_unknown.csv").exists()

    def test_unknown_symbol_when_both_keys_missing(self, tmp_path, monkeypatch):
        events = [{"type": "sig", "action": "TAKE", "regime": "BULLISH"},
                  close_event(r=0.4)]
        telemetry = write_telemetry(tmp_path / "telem.jsonl", events)
        out_dir = tmp_path / "out"
        run_trainer(monkeypatch, telemetry, out_dir)
        assert (out_dir / "meta_label_regime_table_unknown.csv").exists()

    def test_ea_files_dir_is_created_if_missing(self, tmp_path, monkeypatch):
        telemetry = write_telemetry(tmp_path / "telem.jsonl", make_trades(3))
        out_dir = tmp_path / "out"
        ea_dir = tmp_path / "deeply" / "nested" / "Files"
        run_trainer(monkeypatch, telemetry, out_dir, ea_files_dir=ea_dir)
        assert ea_dir.is_dir()
        assert (ea_dir / "meta_label_regime_table_Crash_1000_Index.csv").exists()

    def test_no_telemetry_writes_nothing(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "out"
        missing = tmp_path / "nope.jsonl"
        run_trainer(monkeypatch, missing, out_dir)
        assert not out_dir.exists()

    def test_autodiscovers_terminal_files_dirs_from_appdata(
            self, tmp_path, monkeypatch):
        # Fake %APPDATA% with two installed terminals; the trainer must find
        # every <APPDATA>/MetaQuotes/Terminal/*/MQL5/Files without any flag.
        telemetry = write_telemetry(tmp_path / "telem.jsonl",
                                    make_trades(3, sym="Boom 1000 Index"))
        appdata = tmp_path / "appdata"
        term_a = appdata / "MetaQuotes" / "Terminal" / "HASH_A" / "MQL5" / "Files"
        term_b = appdata / "MetaQuotes" / "Terminal" / "HASH_B" / "MQL5" / "Files"
        term_a.mkdir(parents=True)
        term_b.mkdir(parents=True)

        run_trainer(monkeypatch, telemetry, tmp_path / "out", appdata=appdata)

        tagged = "meta_label_regime_table_Boom_1000_Index.csv"
        assert (term_a / tagged).exists()
        assert (term_b / tagged).exists()

    def test_autodiscovery_tolerates_missing_appdata(
            self, tmp_path, monkeypatch):
        telemetry = write_telemetry(tmp_path / "telem.jsonl", make_trades(3))
        monkeypatch.delenv("APPDATA", raising=False)
        out_dir = tmp_path / "out"
        # must not raise; local out-dir artifacts are still produced
        run_trainer(monkeypatch, telemetry, out_dir)
        assert (out_dir / "meta_label_regime_table.csv").exists()

    def test_unwritable_ea_target_does_not_crash(self, tmp_path, monkeypatch):
        telemetry = write_telemetry(tmp_path / "telem.jsonl", make_trades(3))
        out_dir = tmp_path / "out"
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir")          # mkdir(parents) will fail
        run_trainer(monkeypatch, telemetry, out_dir, ea_files_dir=blocker)
        # local artifacts survive the EA-copy failure
        assert (out_dir / "meta_label_regime_table.csv").exists()
