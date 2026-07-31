"""Read calibration buffer stats from persisted DecisionEngine state files.

This script is called by the Next.js API route /api/system/calibration-stats
to surface the calibration buffer fill level in the Pipeline Diagnostics panel.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def get_calibration_stats(engine_root: str) -> dict[str, object]:
    """Return calibration buffer stats for all persisted engine states.

    Scans ``data/model_state/*.json`` for DecisionEngine state files and
    extracts the calibration buffer size (number of predictions/outcomes).
    """
    state_dir = Path(engine_root) / "data" / "model_state"
    result: dict[str, object] = {}

    if not state_dir.exists():
        return result

    for state_file in sorted(state_dir.glob("*.json")):
        if state_file.name == ".gitkeep":
            continue
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            cal = data.get("calibration", {})
            predictions = cal.get("predictions", [])
            outcomes = cal.get("outcomes", [])
            model = data.get("model", {})
            versioning = data.get("versioning", {})

            # Compute positive/negative outcome ratio
            positive_count = sum(1 for o in outcomes if o == 1)
            negative_count = sum(1 for o in outcomes if o == 0)
            total = len(predictions)

            # Compute average prediction (model confidence calibration)
            avg_prediction = sum(predictions) / total if total > 0 else 0.0

            # Compute prediction accuracy (how well model predicts outcomes)
            correct = sum(
                1
                for p, o in zip(predictions, outcomes)
                if (p >= 0.5 and o == 1) or (p < 0.5 and o == 0)
            )
            accuracy = correct / total if total > 0 else 0.0

            # File metadata for persistence indicator
            file_stat = state_file.stat()
            file_size_bytes = file_stat.st_size
            last_modified_epoch = file_stat.st_mtime

            # Key is derived from filename (e.g. R_100_sniper.json → R_100_sniper)
            key = state_file.stem

            result[key] = {
                "total_samples": total,
                "positive_count": positive_count,
                "negative_count": negative_count,
                "avg_prediction": round(avg_prediction, 4),
                "accuracy": round(accuracy, 4),
                "model_updates": model.get("updates", 0),
                "model_version": model.get("metadata", {}).get("version", "unknown"),
                "ready": total >= 30,  # IsotonicRegression needs 30+ samples
                "progress_pct": min(round(total / 30 * 100, 1), 100.0),
                # Persistence metadata
                "loaded_from_disk": total > 0 or model.get("updates", 0) > 0,
                "save_count": versioning.get("save_count", 0),
                "brier_score": versioning.get("brier_score"),
                "last_save_epoch": last_modified_epoch,
                "last_save_age_seconds": round(
                    time.time() - last_modified_epoch, 0
                ),
                "file_size_bytes": file_size_bytes,
            }
        except Exception as e:
            result[state_file.stem] = {"error": str(e)}

    return result


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    print(json.dumps(get_calibration_stats(root)))
