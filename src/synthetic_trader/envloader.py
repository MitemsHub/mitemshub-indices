"""Load project ``.env.local`` files into the process environment.

The engine reads all credentials with ``os.getenv`` (``DERIV_APP_ID``,
``DERIV_API_TOKEN``, ``SYNTHETIC_MT5_SERVER``, ...).  The dashboard's Next.js
server loads ``external/mitemshub-indices/.env.local`` natively and forwards
the vars to the Python subprocesses it spawns — so dashboard-spawned runs
work.  But direct runs — the CLI from a shell, the scheduled
collector/auto-scorer tasks, ``collect-live-ticks`` — inherit only the
ambient shell env and never see the file, which is why those paths report
"MT5 not configured" even after the user fills in credentials.

This module is a zero-dependency loader (``dependencies = []`` in
``pyproject.toml``) that fixes that: it locates the repo root, parses every
candidate ``.env``/``.env.local`` file (root + the Next.js app), and sets any
variable that is not already present in the environment — standard dotenv
behavior, so an explicitly exported value always wins.

Hooked from :func:`synthetic_trader.cli.main` so every CLI entry point (and
therefore every scheduled task) picks up the file automatically.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Repo root = three parents up from this file (<root>/src/synthetic_trader/).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Candidates in load order (first definition wins, matching dotenv).
_ENV_FILES = (
    _REPO_ROOT / ".env.local",
    _REPO_ROOT / ".env",
    _REPO_ROOT / "external" / "mitemshub-indices" / ".env.local",
    _REPO_ROOT / "external" / "mitemshub-indices" / ".env",
)

_LOADED = False

# KEY=value with optional surrounding quotes; section headers ([name]) and
# inline comments (# ...) are tolerated.
_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse dotenv text into a dict, ignoring comments, blanks and section
    headers (``[TEMPLATE]``).  Values may be single/double-quoted; quotes are
    stripped, other characters are kept verbatim."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        match = _LINE_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        # Strip a trailing inline comment only when it follows whitespace
        # AND the value is not quoted (a quoted value is literal, so a
        # ` # ` inside quotes must survive, e.g. A="x # y").
        if not value.startswith(('"', "'")):
            value = re.sub(r"\s+#.*$", "", value)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value.strip()
    return out


def candidate_env_files() -> list[Path]:
    """The .env files this loader would read, in priority order (existing
    first)."""
    return [p for p in _ENV_FILES if p.is_file()]


def load_env_files(overwrite: bool = False) -> int:
    """Load every candidate ``.env``/``.env.local`` into ``os.environ``.

    Set variables are only overwritten when ``overwrite=True`` (default
    False — an exported variable always wins).  Returns the number of
    variables that were newly set.  Idempotent: repeated calls are no-ops
    unless ``overwrite=True``.
    """
    global _LOADED
    if _LOADED and not overwrite:
        return 0
    count = 0
    for path in candidate_env_files():
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        for key, value in parse_dotenv(text).items():
            if overwrite or key not in os.environ:
                os.environ[key] = value
                count += 1
    _LOADED = True
    return count


def main() -> None:
    """CLI smoke: print which files were found and how many vars were set."""
    files = candidate_env_files()
    print(f"env files found: {len(files)}")
    for path in files:
        print(f"  {path}")
    print(f"vars set: {load_env_files()}")
    for key in ("DERIV_APP_ID", "DERIV_API_TOKEN", "SYNTHETIC_MT5_SERVER",
                "SYNTHETIC_MT5_LOGIN", "SYNTHETIC_MT5_PASSWORD"):
        present = key in os.environ
        print(f"{key}: {'set' if present else 'missing'}")


if __name__ == "__main__":  # pragma: no cover - manual smoke entry
    main()
