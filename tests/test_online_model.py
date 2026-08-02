from __future__ import annotations

import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from synthetic_trader.cli import main
from synthetic_trader.models.online import OnlineLogisticModel
from synthetic_trader.models.replay_buffer import ExperienceReplayBuffer


class OnlineModelTests(unittest.TestCase):
    def test_update_moves_probability_toward_label(self) -> None:
        model = OnlineLogisticModel()
        features = {"slope_20_atr": 1.0, "bos_up": 1.0}
        before = model.predict_proba(features)
        for _ in range(10):
            model.update(features, label=1)
        after = model.predict_proba(features)

        self.assertGreater(after, before)
        self.assertEqual(model.updates, 10)

    def test_model_save_and_load_round_trip_preserves_weights_and_metadata(self) -> None:
        model = OnlineLogisticModel()
        model.update({"atr_ratio": 1.2, "structure_bias": 0.5}, label=1)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.json"
            model.save(path, metadata={"symbol": "R_75", "source": "unit-test"})
            loaded = OnlineLogisticModel.load(path)

        self.assertEqual(loaded.weights, model.weights)
        self.assertEqual(loaded.bias, model.bias)
        self.assertEqual(loaded.metadata["symbol"], "R_75")
        self.assertEqual(loaded.metadata["source"], "unit-test")

    def test_backtest_command_can_load_and_save_model_artifact(self) -> None:
        seed = OnlineLogisticModel()
        seed.weights["seed_only"] = 0.75

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "ticks.csv"
            model_in = Path(tmpdir) / "seed.json"
            model_out = Path(tmpdir) / "trained.json"
            _write_ticks_csv(csv_path, candles=130)
            seed.save(model_in)

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "backtest",
                        "--csv",
                        str(csv_path),
                        "--symbol",
                        "R_75",
                        "--timeframe",
                        "60",
                        "--model-load",
                        str(model_in),
                        "--model-save",
                        str(model_out),
                    ]
                )

            saved = OnlineLogisticModel.load(model_out)

        self.assertEqual(exit_code, 0)
        self.assertIn("model_saved=", output.getvalue())
        self.assertIn("seed_only", saved.weights)
        self.assertEqual(saved.metadata["command"], "backtest")
        self.assertEqual(saved.metadata["symbol"], "R_75")

    def test_walk_forward_command_can_load_and_save_model_artifact(self) -> None:
        seed = OnlineLogisticModel()
        seed.weights["seed_only"] = 0.25

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "ticks.csv"
            model_in = Path(tmpdir) / "seed.json"
            model_out = Path(tmpdir) / "walk-forward-model.json"
            _write_ticks_csv(csv_path, candles=270)
            seed.save(model_in)

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "walk-forward",
                        "--csv",
                        str(csv_path),
                        "--symbol",
                        "R_75",
                        "--train-ticks",
                        "520",
                        "--test-ticks",
                        "400",
                        "--timeframe",
                        "60",
                        "--higher-timeframe",
                        "300",
                        "--model-load",
                        str(model_in),
                        "--model-save",
                        str(model_out),
                    ]
                )

            saved = OnlineLogisticModel.load(model_out)

        self.assertEqual(exit_code, 0)
        self.assertIn("folds=", output.getvalue())
        self.assertIn("seed_only", saved.weights)
        self.assertEqual(saved.metadata["command"], "walk-forward")
        self.assertEqual(saved.metadata["symbol"], "R_75")

    def test_prepare_live_model_command_collects_history_and_saves_seeded_model(self) -> None:
        from synthetic_trader.data.tick_store import inspect_ticks, write_ticks_csv
        from tests.test_backtest import synthetic_ticks

        async def fake_collect_history(
            *,
            symbol: str,
            count: int,
            output_path: str,
            app_id: str | None,
            batch_size: int,
            append: bool,
        ):
            del count, app_id, batch_size
            ticks = synthetic_ticks(symbol=symbol, candles=130)
            write_ticks_csv(output_path, ticks, append=append)
            return inspect_ticks(ticks, symbol=symbol)

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "r100_ticks.csv"
            model_path = Path(tmpdir) / "r100_seed_model.json"

            output = io.StringIO()
            with patch("synthetic_trader.cli.collect_history", side_effect=fake_collect_history):
                with contextlib.redirect_stdout(output):
                    exit_code = main(
                        [
                            "prepare-live-model",
                            "--symbol",
                            "R_100",
                            "--count",
                            "520",
                            "--output",
                            str(csv_path),
                            "--model-save",
                            str(model_path),
                            "--replace",
                        ]
                    )

            saved = OnlineLogisticModel.load(model_path)

        self.assertEqual(exit_code, 0)
        self.assertIn("output=", output.getvalue())
        self.assertIn("model_saved=", output.getvalue())
        self.assertEqual(saved.metadata["command"], "prepare-live-model")
        self.assertEqual(saved.metadata["symbol"], "R_100")


class ReplayBufferCorruptionTests(unittest.TestCase):
    """Validate that ExperienceReplayBuffer.from_dict rejects corrupt data."""

    def _good_dict(self) -> dict:
        return {
            "capacity": 100,
            "mini_batch_size": 8,
            "replay_ratio": 0.2,
            "seen": 5,
            "entries": [
                {"features": {"atr_14": 1.0, "slope": 0.5}, "label": 1, "sample_weight": 1.0},
                {"features": {"atr_14": 0.8}, "label": 0, "sample_weight": 0.5},
            ],
        }

    def test_valid_dict_loads_cleanly(self) -> None:
        buf = ExperienceReplayBuffer.from_dict(self._good_dict())
        self.assertEqual(len(buf), 2)
        self.assertEqual(buf.capacity, 100)
        self.assertEqual(buf.total_seen, 5)

    def test_missing_top_level_keys_use_defaults(self) -> None:
        buf = ExperienceReplayBuffer.from_dict({"entries": []})
        self.assertEqual(buf.capacity, 10_000)  # default
        self.assertEqual(buf.mini_batch_size, 16)  # default
        self.assertEqual(buf.replay_ratio, 0.2)  # default
        self.assertEqual(buf.total_seen, 0)  # default

    def test_negative_capacity_uses_default(self) -> None:
        d = self._good_dict()
        d["capacity"] = -5
        buf = ExperienceReplayBuffer.from_dict(d)
        self.assertEqual(buf.capacity, 10_000)

    def test_string_capacity_uses_default(self) -> None:
        d = self._good_dict()
        d["capacity"] = "not_a_number"
        buf = ExperienceReplayBuffer.from_dict(d)
        self.assertEqual(buf.capacity, 10_000)

    def test_replay_ratio_out_of_range_uses_default(self) -> None:
        d = self._good_dict()
        d["replay_ratio"] = 2.5
        buf = ExperienceReplayBuffer.from_dict(d)
        self.assertEqual(buf.replay_ratio, 0.2)

    def test_negative_seen_uses_default(self) -> None:
        d = self._good_dict()
        d["seen"] = -100
        buf = ExperienceReplayBuffer.from_dict(d)
        self.assertEqual(buf.total_seen, 0)

    def test_entries_not_a_list_uses_empty(self) -> None:
        d = self._good_dict()
        d["entries"] = "garbage"
        buf = ExperienceReplayBuffer.from_dict(d)
        self.assertEqual(len(buf), 0)

    def test_corrupt_entry_skipped_valid_entries_kept(self) -> None:
        d = self._good_dict()
        d["entries"].append({"features": "not_a_dict", "label": 1})
        d["entries"].append({"label": 99})  # missing features
        d["entries"].append({"features": {"x": 1.0}, "label": 3})  # bad label
        buf = ExperienceReplayBuffer.from_dict(d)
        self.assertEqual(len(buf), 2)  # only the 2 good entries

    def test_empty_features_entry_skipped(self) -> None:
        d = self._good_dict()
        d["entries"].append({"features": {}, "label": 1})
        buf = ExperienceReplayBuffer.from_dict(d)
        self.assertEqual(len(buf), 2)

    def test_nan_feature_value_skips_entry(self) -> None:
        import math
        d = self._good_dict()
        d["entries"].append({"features": {"atr": math.nan}, "label": 1})
        buf = ExperienceReplayBuffer.from_dict(d)
        self.assertEqual(len(buf), 2)

    def test_inf_feature_value_skips_entry(self) -> None:
        import math
        d = self._good_dict()
        d["entries"].append({"features": {"atr": math.inf}, "label": 1})
        buf = ExperienceReplayBuffer.from_dict(d)
        self.assertEqual(len(buf), 2)

    def test_negative_sample_weight_defaults_to_one(self) -> None:
        d = self._good_dict()
        d["entries"][0]["sample_weight"] = -1.0
        buf = ExperienceReplayBuffer.from_dict(d)
        self.assertEqual(len(buf), 2)
        self.assertEqual(buf._buffer[0].sample_weight, 1.0)

    def test_nan_sample_weight_defaults_to_one(self) -> None:
        import math
        d = self._good_dict()
        d["entries"][0]["sample_weight"] = math.nan
        buf = ExperienceReplayBuffer.from_dict(d)
        self.assertEqual(len(buf), 2)
        self.assertEqual(buf._buffer[0].sample_weight, 1.0)

    def test_completely_empty_dict_returns_empty_buffer(self) -> None:
        buf = ExperienceReplayBuffer.from_dict({})
        self.assertEqual(len(buf), 0)
        self.assertEqual(buf.capacity, 10_000)

    def test_load_from_corrupt_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "corrupt.json"
            path.write_text("{invalid json!!!", encoding="utf-8")
            with self.assertRaises(Exception):
                ExperienceReplayBuffer.load(path)


def _write_ticks_csv(path: Path, candles: int, symbol: str = "R_75") -> None:
    from tests.test_backtest import synthetic_ticks

    ticks = synthetic_ticks(symbol=symbol, candles=candles)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["epoch", "price", "symbol"])
        writer.writeheader()
        for tick in ticks:
            writer.writerow({"epoch": tick.epoch, "price": tick.price, "symbol": tick.symbol})


if __name__ == "__main__":
    unittest.main()
