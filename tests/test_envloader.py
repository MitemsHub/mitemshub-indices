"""Tests for the zero-dependency ``.env.local`` loader (envloader.py).

The loader is what makes direct Python runs (CLI, scheduled tasks) see the
same credentials the dashboard's Next.js server forwards to subprocesses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from synthetic_trader.envloader import parse_dotenv


class TestParseDotenv:
    def test_basic_key_value(self) -> None:
        out = parse_dotenv("FOO=bar\nBAZ=qux\n")
        assert out == {"FOO": "bar", "BAZ": "qux"}

    def test_comments_blanks_and_sections(self) -> None:
        text = """
# a comment
[TEMPLATE]

FOO=bar

# another comment
BAR=42
"""
        assert parse_dotenv(text) == {"FOO": "bar", "BAR": "42"}

    def test_quotes_are_stripped(self) -> None:
        out = parse_dotenv("A=\"hello world\"\nB='single'\n")
        assert out == {"A": "hello world", "B": "single"}

    def test_inline_comment_and_no_value(self) -> None:
        out = parse_dotenv("A=value # trailing\nEMPTY=\n")
        assert out["A"] == "value"
        assert out["EMPTY"] == ""

    def test_quoted_value_with_inline_hash_survives(self) -> None:
        """A ` # ` inside quotes is literal, not a comment: A="x # y" → x # y."""
        out = parse_dotenv('A="x # y"\n')
        assert out["A"] == "x # y"

    def test_bom_and_crlf(self, tmp_path: Path, monkeypatch) -> None:
        """The file reader strips a UTF-8 BOM and splitlines handles CRLF."""
        from synthetic_trader import envloader

        env_file = tmp_path / "bom.env"
        env_file.write_bytes("\ufeffA=one\r\nB=two\r\n".encode("utf-8"))
        monkeypatch.setattr(envloader, "_ENV_FILES", (env_file,))
        monkeypatch.setattr(envloader, "_LOADED", False)
        monkeypatch.delenv("A", raising=False)
        monkeypatch.delenv("B", raising=False)

        count = envloader.load_env_files()
        assert count == 2
        assert envloader.os.environ["A"] == "one"
        assert envloader.os.environ["B"] == "two"

    def test_garbage_lines_ignored(self) -> None:
        out = parse_dotenv("not a pair\n=novalue\nFOO==double\n")
        # FOO==double splits at the first '=' → value "=double"
        assert out.get("FOO") == "=double"


class TestLoadEnvFiles:
    # load_env_files writes directly to os.environ, which monkeypatch does not
    # auto-undo; deleting the keys up front (raising=False) makes monkeypatch
    # restore them to absent at teardown, isolating each test.
    _TEST_KEYS = ("A", "B", "KEEP")

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch) -> None:
        for key in self._TEST_KEYS:
            monkeypatch.delenv(key, raising=False)

    def test_sets_missing_vars_only(self, tmp_path: Path, monkeypatch) -> None:
        from synthetic_trader import envloader

        env_file = tmp_path / "custom.env"
        env_file.write_text("A=from_file\nKEEP=file_value\n", encoding="utf-8")
        monkeypatch.setattr(envloader, "_ENV_FILES", (env_file,))
        monkeypatch.setattr(envloader, "_LOADED", False)
        monkeypatch.setenv("KEEP", "exported_value")  # exported must win

        count = envloader.load_env_files()
        assert count == 1  # only A was new
        assert envloader.os.environ["A"] == "from_file"
        assert envloader.os.environ["KEEP"] == "exported_value"

    def test_overwrite_flag(self, tmp_path: Path, monkeypatch) -> None:
        from synthetic_trader import envloader

        env_file = tmp_path / "custom.env"
        env_file.write_text("A=from_file\n", encoding="utf-8")
        monkeypatch.setattr(envloader, "_ENV_FILES", (env_file,))
        monkeypatch.setattr(envloader, "_LOADED", False)
        monkeypatch.setenv("A", "exported_value")

        envloader.load_env_files()  # no overwrite
        assert envloader.os.environ["A"] == "exported_value"
        envloader.load_env_files(overwrite=True)  # overwrite
        assert envloader.os.environ["A"] == "from_file"

    def test_idempotent_without_overwrite(self, tmp_path: Path, monkeypatch) -> None:
        from synthetic_trader import envloader

        env_file = tmp_path / "custom.env"
        env_file.write_text("A=1\nB=2\n", encoding="utf-8")
        monkeypatch.setattr(envloader, "_ENV_FILES", (env_file,))
        monkeypatch.setattr(envloader, "_LOADED", False)

        first = envloader.load_env_files()
        second = envloader.load_env_files()
        assert first == 2
        assert second == 0  # already loaded → no-op

    def test_missing_files_are_skipped(self, tmp_path: Path, monkeypatch) -> None:
        from synthetic_trader import envloader

        missing = tmp_path / "does_not_exist.env"
        monkeypatch.setattr(envloader, "_ENV_FILES", (missing,))
        monkeypatch.setattr(envloader, "_LOADED", False)
        assert envloader.load_env_files() == 0


def test_cli_main_loads_env(tmp_path: Path, monkeypatch) -> None:
    """The CLI main() must load env files before running any command — this is
    the hook that makes scheduled tasks see .env.local credentials."""
    from synthetic_trader import cli, envloader

    called = []
    real_load = envloader.load_env_files

    def fake_load(overwrite: bool = False) -> int:
        called.append(overwrite)
        return real_load(overwrite)

    monkeypatch.setattr(envloader, "load_env_files", fake_load)
    # A command that fails fast without touching the network/MT5.
    rc = cli.main(["inspect-data", "--csv", "data/backfill/R_75_ticks.csv"])
    assert rc == 0
    assert called, "cli.main() must call load_env_files() before handling commands"
