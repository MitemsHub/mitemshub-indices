from __future__ import annotations

from pathlib import Path

import pytest

from scripts import artifact_spec
from scripts.verify_go_live_artifacts import verify


ROOT = Path(__file__).resolve().parents[1]


def test_go_live_repository_artifacts_pass() -> None:
    result = verify()
    assert result["ok"], result["problems"]
    assert result["deployed_byte_identical"] is None
    assert result["repo_live_sha256"] is not None
    assert len(result["repo_live_sha256"]) == 64


def test_custom_data_dir_requires_all_specs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CERT_DATA_DIR", "artifacts/v100_replay")
    monkeypatch.delenv("CERT_SPREAD", raising=False)
    monkeypatch.delenv("CERT_USD_PER_UNIT_PER_LOT", raising=False)
    monkeypatch.delenv("CERT_MIN_LOT", raising=False)
    monkeypatch.delenv("CERT_LOT_STEP", raising=False)

    with pytest.raises(SystemExit, match="SPEC-INTEGRITY FAIL"):
        artifact_spec.assert_spec_integrity()


def test_custom_data_dir_stamp_records_explicit_specs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CERT_DATA_DIR", "artifacts/v100_replay")
    monkeypatch.setenv("CERT_SPREAD", "0.26")
    monkeypatch.setenv("CERT_USD_PER_UNIT_PER_LOT", "1.0")
    monkeypatch.setenv("CERT_MIN_LOT", "1.0")
    monkeypatch.setenv("CERT_LOT_STEP", "1.0")

    stamp = artifact_spec.spec_block(artifact="test", symbol="Volatility 100 Index")
    assert stamp["symbol"] == "Volatility 100 Index"
    assert stamp["spread"] == 0.26
    assert stamp["min_lot"] == 1.0
    assert all(stamp["explicit_env"].values())
    assert stamp["schema"] == "mitemshub.artifact-spec.v1"
