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
    """Read DecisionEngine state files and return replay buffer statistics.

    Model state is persisted to data/model_state/{symbol}_{mode}.json
    by the _maybe_save_engine_state() function in market_snapshot.py.

    The state file structure is:
    {
      "model": {
        "replay_buffer": { ... },
        "weights": { ... },
        "updates": N,
        ...
      },
      "calibration": { ... },
      "versioning": { ... },
    }
    """
    state_dir = Path(engine_root) / "data" / "model_state"
    stats = {}

    for symbol in ("r_75", "r_100"):
        # Model state is saved as {symbol}_sniper.json (sniper-only mode)
        model_path = state_dir / f"{symbol}_sniper.json"
        if not model_path.exists():
            stats[symbol] = None
            continue

        try:
            data = json.loads(model_path.read_text(encoding="utf-8"))
            model_section = data.get("model", {})
            buf_payload = model_section.get("replay_buffer")

            if buf_payload is None:
                # No replay buffer persisted — show empty state
                stats[symbol] = {
                    "buffer_size": 0,
                    "capacity": 10_000,
                    "fill_pct": 0.0,
                    "total_seen": 0,
                    "mini_batch_size": 16,
                    "replay_ratio": 0.2,
                    "label_0_count": 0,
                    "label_1_count": 0,
                    "label_balance": 0.5,
                    "model_updates": model_section.get("updates", 0),
                    "model_version": model_section.get("metadata", {}).get("version", "0.1.0"),
                }
                continue

            # Parse the replay buffer dict directly
            entries = buf_payload.get("entries", [])
            capacity = buf_payload.get("capacity", 10_000)
            total_seen = buf_payload.get("seen", 0)
            mini_batch_size = buf_payload.get("mini_batch_size", 16)
            replay_ratio = buf_payload.get("replay_ratio", 0.2)
            buffer_size = len(entries)

            # Compute label distribution from entries
            label_0 = sum(1 for e in entries if e.get("label", 0) == 0)
            label_1 = sum(1 for e in entries if e.get("label", 0) == 1)
            total_labels = label_0 + label_1 or 1

            stats[symbol] = {
                "buffer_size": buffer_size,
                "capacity": capacity,
                "fill_pct": round(buffer_size / capacity * 100, 1) if capacity > 0 else 0,
                "total_seen": total_seen,
                "mini_batch_size": mini_batch_size,
                "replay_ratio": replay_ratio,
                "label_0_count": label_0,
                "label_1_count": label_1,
                "label_balance": round(label_0 / total_labels, 3),
                "model_updates": model_section.get("updates", 0),
                "model_version": model_section.get("metadata", {}).get("version", "0.1.0"),
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
