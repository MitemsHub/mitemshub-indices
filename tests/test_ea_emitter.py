from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from synthetic_trader.execution.ea_emitter import (
    EA_DEFAULT_MAGIC,
    build_call_record,
    call_file_path,
    clear_call_file,
    emit_call_from_alert,
    make_ea_call_id,
    mt5_common_files_dir,
    read_ea_state,
    state_file_path,
    write_call_file,
)


def _proven_alert(**overrides: object) -> dict[str, object]:
    """A Stage-3-gated buy candidate with proven evidence."""
    alert: dict[str, object] = {
        "symbol": "R_75",
        "call": "buy_candidate",
        "direction_bias": "buy",
        "entry": 1820.5,
        "stop_loss": 1818.0,
        "take_profit": 1826.0,
        "execution_stop": 1818.0,
        "primary_target": 1826.0,
        "hold_horizon_minutes": 60,
        "generated_at": "2026-08-11T10:30:00",
        "reward_risk": 4.0,
        "stage3": {
            "evidence_status": "proven",
            "execution_allowed": True,
            "sizing": {"multiplier": 1.0, "level": "full"},
        },
        "execution_allowed": True,
    }
    alert.update(overrides)
    return alert


class EaEmitterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.files_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_build_call_record_maps_level_aliases(self) -> None:
        record = build_call_record(
            _proven_alert(),
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.2,
        )
        self.assertEqual(record["symbol"], "R_75")
        self.assertEqual(record["venue_symbol"], "SYN75")
        self.assertEqual(record["direction"], "buy")
        self.assertEqual(record["entry"], 1820.5)
        self.assertEqual(record["stop_loss"], 1818.0)
        self.assertEqual(record["take_profit"], 1826.0)
        self.assertEqual(record["volume"], 0.2)
        self.assertEqual(record["magic"], EA_DEFAULT_MAGIC)
        self.assertEqual(record["evidence_status"], "proven")
        self.assertEqual(record["horizon_sec"], 3600)
        self.assertTrue(record["expiry_epoch"] > record["issued_at_epoch"])

    def test_build_call_record_falls_back_to_stop_loss_and_take_profit(self) -> None:
        alert = _proven_alert()
        alert.pop("execution_stop")
        alert.pop("primary_target")
        record = build_call_record(alert, symbol="R_75", venue_symbol="SYN75", volume=0.2)
        self.assertEqual(record["stop_loss"], 1818.0)
        self.assertEqual(record["take_profit"], 1826.0)

    def test_emit_proven_call_writes_atomic_json(self) -> None:
        alert = _proven_alert()
        record = emit_call_from_alert(
            alert,
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.2,
            files_dir=self.files_dir,
        )
        self.assertIsNotNone(record)
        path = call_file_path("R_75", self.files_dir)
        self.assertTrue(path.exists())
        # No stray temp files left behind (atomic write).
        self.assertEqual(list(self.files_dir.glob("*.tmp")), [])
        parsed = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(parsed["call_id"], record["call_id"])
        self.assertEqual(parsed["direction"], "buy")
        self.assertEqual(parsed["venue_symbol"], "SYN75")

    def test_emit_held_back_when_not_proven(self) -> None:
        alert = _proven_alert()
        alert["stage3"] = {
            "evidence_status": "still_learning",
            "execution_allowed": False,
            "sizing": {"multiplier": 0.5, "level": "half"},
        }
        alert["execution_allowed"] = False
        record = emit_call_from_alert(
            alert,
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.2,
            files_dir=self.files_dir,
        )
        self.assertIsNone(record)
        self.assertFalse(call_file_path("R_75", self.files_dir).exists())

    def test_emit_held_back_when_gate_disallows_execution(self) -> None:
        alert = _proven_alert()
        alert["stage3"] = {
            "evidence_status": "proven",
            "execution_allowed": False,
            "sizing": {"multiplier": 1.0, "level": "full"},
        }
        alert["execution_allowed"] = False
        record = emit_call_from_alert(
            alert,
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.2,
            files_dir=self.files_dir,
        )
        self.assertIsNone(record)

    def test_emit_held_back_when_not_a_candidate(self) -> None:
        alert = _proven_alert(call="stand_aside")
        record = emit_call_from_alert(
            alert,
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.2,
            files_dir=self.files_dir,
        )
        self.assertIsNone(record)

    def test_emit_held_back_on_unordered_levels(self) -> None:
        alert = _proven_alert()
        alert["entry"] = 1820.5
        alert["stop_loss"] = 1822.0  # stop above entry for a buy — invalid
        alert["execution_stop"] = 1822.0
        record = emit_call_from_alert(
            alert,
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.2,
            files_dir=self.files_dir,
        )
        self.assertIsNone(record)

    def test_sell_alert_orders_levels_correctly(self) -> None:
        alert = _proven_alert(
            call="sell_candidate",
            direction_bias="sell",
            entry=1820.5,
            stop_loss=1823.0,
            take_profit=1815.0,
            execution_stop=1823.0,
            primary_target=1815.0,
        )
        record = emit_call_from_alert(
            alert,
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.2,
            files_dir=self.files_dir,
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["direction"], "sell")
        self.assertTrue(record["take_profit"] < record["entry"] < record["stop_loss"])

    def test_require_proven_false_allows_still_learning(self) -> None:
        alert = _proven_alert()
        alert["stage3"] = {
            "evidence_status": "still_learning",
            "execution_allowed": True,
            "sizing": {"multiplier": 0.5, "level": "half"},
        }
        record = emit_call_from_alert(
            alert,
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.2,
            files_dir=self.files_dir,
            require_proven=False,
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["evidence_status"], "still_learning")

    def test_write_call_file_replaces_previous_call(self) -> None:
        first = build_call_record(
            _proven_alert(),
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.2,
        )
        second = build_call_record(
            _proven_alert(entry=1821.0),
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.2,
        )
        write_call_file(first, files_dir=self.files_dir)
        write_call_file(second, files_dir=self.files_dir)
        path = call_file_path("R_75", self.files_dir)
        parsed = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(parsed["entry"], 1821.0)
        self.assertEqual(len(list(self.files_dir.glob("synth_calls_R_75.json*"))), 1)

    def test_write_call_file_is_idempotent_for_same_trade(self) -> None:
        first = build_call_record(
            _proven_alert(),
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.2,
        )
        # Same direction + levels, but a fresh generated_at (simulates a poll
        # re-emitting the same still-alive plan).
        second = build_call_record(
            _proven_alert(generated_at="2026-08-11T10:35:00"),
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.2,
        )
        write_call_file(first, files_dir=self.files_dir)
        write_call_file(second, files_dir=self.files_dir)
        path = call_file_path("R_75", self.files_dir)
        parsed = json.loads(path.read_text(encoding="utf-8"))
        # The first record survives untouched — the EA dedupes by call_id, so a
        # re-emit with a new id would re-open the same trade after a close.
        self.assertEqual(parsed["call_id"], first["call_id"])
        self.assertEqual(parsed["entry"], first["entry"])

    def test_read_ea_state_roundtrip(self) -> None:
        state_path = state_file_path("R_75", self.files_dir)
        state_path.write_text(
            json.dumps({"call_id": "x", "status": "executed", "open_ticket": 123}),
            encoding="utf-8",
        )
        state = read_ea_state("R_75", files_dir=self.files_dir)
        self.assertIsNotNone(state)
        self.assertEqual(state["status"], "executed")
        self.assertEqual(state["open_ticket"], 123)

    def test_read_ea_state_missing_returns_none(self) -> None:
        self.assertIsNone(read_ea_state("R_100", files_dir=self.files_dir))

    def test_clear_call_file(self) -> None:
        write_call_file(
            build_call_record(_proven_alert(), symbol="R_75", venue_symbol="SYN75", volume=0.2),
            files_dir=self.files_dir,
        )
        self.assertTrue(clear_call_file("R_75", files_dir=self.files_dir))
        self.assertFalse(call_file_path("R_75", self.files_dir).exists())

    def test_make_ea_call_id_is_deterministic(self) -> None:
        cid = make_ea_call_id("R_75", "2026-08-11T10:30:00", "buy")
        self.assertEqual(cid, "R_75_2026-08-11-10-30-00_buy")
        self.assertEqual(cid, make_ea_call_id("R_75", "2026-08-11T10:30:00", "buy"))

    def test_make_ea_call_id_falls_back_to_wall_clock_when_generated_at_missing(self) -> None:
        # Raw snapshots do not always carry generated_at; a constant id would
        # make the EA dedupe suppress every later call of that type.  The
        # fallback embeds sub-second precision, so ids are unique across
        # calls at least a millisecond apart (emits are seconds apart in
        # practice, and same-trade re-emits are deduped before this runs).
        cid = make_ea_call_id("R_75", None, "buy")
        self.assertTrue(cid.startswith("R_75_"))
        self.assertTrue(cid.endswith("_buy"))
        # Contains the sub-second component (millisecond digits) — i.e. NOT
        # the plain second-granular fallback that would collide.
        self.assertRegex(cid, r"\d{3}_buy$")
        cid2 = make_ea_call_id("R_75", None, "buy")
        self.assertTrue(cid2.startswith("R_75_"))

    def test_mt5_common_files_dir_env_override(self) -> None:
        os.environ["SYNTH_EA_FILES_DIR"] = str(self.files_dir)
        try:
            self.assertEqual(mt5_common_files_dir(), self.files_dir)
        finally:
            del os.environ["SYNTH_EA_FILES_DIR"]

    def test_call_file_names_per_symbol(self) -> None:
        self.assertEqual(call_file_path("R_75", self.files_dir).name, "synth_calls_R_75.json")
        self.assertEqual(state_file_path("R_100", self.files_dir).name, "synth_ea_state_R_100.json")


if __name__ == "__main__":
    unittest.main()
