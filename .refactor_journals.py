"""Replace hardcoded 'journals/' paths with temp dir references in test files."""
import re

# File 1: test_live_market_snapshot.py
path = r"C:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_live_market_snapshot.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace Path("journals/...") with _JOURNAL_DIR / "..."
content = re.sub(
    r'Path\("journals/([^"]+)"\)',
    r'_JOURNAL_DIR / "\1"',
    content,
)

# Replace journal_path="journals/..." with journal_path=str(_JOURNAL_DIR / "...")
content = re.sub(
    r'journal_path="journals/([^"]+)"',
    r'journal_path=str(_JOURNAL_DIR / "\1")',
    content,
)

# Replace the "journals/does_not_exist.jsonl" string arg
content = content.replace(
    '"journals/does_not_exist.jsonl"',
    'str(_JOURNAL_DIR / "does_not_exist.jsonl")',
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print(f"Updated {path}")

# File 2: test_cli_calibration_logging.py
path2 = r"C:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_cli_calibration_logging.py"
with open(path2, "r", encoding="utf-8") as f:
    content2 = f.read()

# Add import + _JOURNAL_DIR after imports
content2 = re.sub(
    r'(from pathlib import Path\n)',
    r'\1import tempfile\nfrom pathlib import Path as _Path\n\n_JOURNAL_DIR = _Path(tempfile.mkdtemp(prefix="mitems-test-journals-"))\n',
    content2,
)

# Replace the hardcoded journal path
content2 = re.sub(
    r'"journals/live_calibration_calls.jsonl"',
    r'str(_JOURNAL_DIR / "live_calibration_calls.jsonl")',
    content2,
)

with open(path2, "w", encoding="utf-8") as f:
    f.write(content2)

print(f"Updated {path2}")
