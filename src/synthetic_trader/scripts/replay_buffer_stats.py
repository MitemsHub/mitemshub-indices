"""Read the live model artifact and output replay buffer stats as JSON.

Usage (called from Node.js via runPythonScript):
    python -c "import sys; sys.path.insert(0, 'src'); ..."

The script looks for model artifacts at:
    {engine_root}/artifacts/{symbol}_live_seed_model.json

It loads the model, inspects the replay buffer, and prints a JSON object
with the buffer statistics to stdout.
"""

import json
import sys
from pathlib import Path


def get_replay_buffer_stats(engine_root: str) -> dict:
    """Read model artifacts and return replay buffer statistics."""
    artifacts_dir = Path(engine_root) / "artifacts"
    stats = {}

    for symbol in ("r_75", "r_100"):
        # Try both naming conventions: r_75_live_seed_model.json and r75_live_seed_model.json
        model_path = artifacts_dir / f"{symbol}_live_seed_model.json"
        if not model_path.exists():
            model_path = artifacts_dir / f"{symbol.replace('_', '')}_live_seed_model.json"
        if not model_path.exists():
            stats[symbol] = None
            continue

        try:
            sys.path.insert(0, str(Path(engine_root) / "src"))
            from synthetic_trader.models.online import OnlineLogisticModel

            model = OnlineLogisticModel.load(model_path)
            buf = model.replay_buffer

            label_dist = buf.label_distribution
            total_labels = sum(label_dist.values()) or 1

            stats[symbol] = {
                "buffer_size": len(buf),
                "capacity": buf.capacity,
                "fill_pct": round(len(buf) / buf.capacity * 100, 1) if buf.capacity > 0 else 0,
                "total_seen": buf.total_seen,
                "mini_batch_size": buf.mini_batch_size,
                "replay_ratio": buf.replay_ratio,
                "label_0_count": label_dist.get(0, 0),
                "label_1_count": label_dist.get(1, 0),
                "label_balance": round(label_dist.get(0, 0) / total_labels, 3),
                "model_updates": model.updates,
                "model_version": model.version,
            }
        except Exception as e:
            stats[symbol] = {"error": str(e)}

    return stats


if __name__ == "__main__":
    engine_root = sys.argv[1] if len(sys.argv) > 1 else ""
    if not engine_root:
        print(json.dumps({"error": "No engine root provided"}))
        sys.exit(1)

    result = get_replay_buffer_stats(engine_root)
    print(json.dumps(result, indent=2))
