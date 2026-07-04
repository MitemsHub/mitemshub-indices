from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from synthetic_trader.journal.trade_journal import TradeJournal


class TradeJournalTests(unittest.TestCase):
    def test_journal_records_rejected_signal_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = TradeJournal(Path(tmpdir) / "journal.jsonl")
            journal.record_rejection(
                symbol="R_75",
                epoch=123.0,
                reasons=("confidence too low", "risk veto"),
                model_version="online-logistic-v1.0",
                confidence=0.41,
            )
            lines = journal.path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["type"], "rejection")
        self.assertEqual(payload["symbol"], "R_75")
        self.assertEqual(payload["reasons"], ["confidence too low", "risk veto"])
        self.assertEqual(payload["confidence"], 0.41)

    def test_journal_records_generic_event_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = TradeJournal(Path(tmpdir) / "journal.jsonl")
            journal.record_event(
                "decision_skip",
                {
                    "symbol": "R_75",
                    "epoch": 456.0,
                    "reasons": ["need 80 candles, have 10"],
                },
            )
            lines = journal.path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["type"], "decision_skip")
        self.assertEqual(payload["symbol"], "R_75")
        self.assertEqual(payload["reasons"], ["need 80 candles, have 10"])


if __name__ == "__main__":
    unittest.main()
