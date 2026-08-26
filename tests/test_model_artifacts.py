from __future__ import annotations

from pathlib import Path

import pytest

from brain.artifacts import resolve_model_artifact, store_model_artifact


def test_resolve_model_artifact_accepts_normalized_local_path(tmp_path: Path) -> None:
    artifact = tmp_path / "models" / "btc.joblib"
    artifact.parent.mkdir()
    artifact.write_text("ok", encoding="utf-8")

    resolved = resolve_model_artifact(str(artifact).replace("/", "\\"))

    assert resolved.exists()


def test_resolve_model_artifact_raises_for_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.joblib"

    with pytest.raises(ValueError, match="artifact_not_found"):
        resolve_model_artifact(str(missing))


def _use_relative_model_root(monkeypatch, tmp_path: Path) -> None:
    """Chdir into tmp_path and point MODEL_ARTIFACT_ROOT at the relative "models" dir,
    mirroring the production default (`Path("models")` relative to the process cwd)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("brain.artifacts.MODEL_ARTIFACT_ROOT", Path("models"))


def test_store_model_artifact_copies_into_model_root(tmp_path: Path, monkeypatch) -> None:
    _use_relative_model_root(monkeypatch, tmp_path)

    source = tmp_path / "outside" / "trained.joblib"
    source.parent.mkdir()
    source.write_bytes(b"model-bytes")

    artifact_uri = store_model_artifact(source)

    stored_path = tmp_path / "models" / "trained.joblib"
    assert artifact_uri == "models/trained.joblib"
    assert stored_path.read_bytes() == b"model-bytes"


def test_store_model_artifact_respects_object_path(tmp_path: Path, monkeypatch) -> None:
    _use_relative_model_root(monkeypatch, tmp_path)

    source = tmp_path / "outside" / "trained.joblib"
    source.parent.mkdir()
    source.write_bytes(b"model-bytes")

    artifact_uri = store_model_artifact(source, object_path="AAPL/trained_v2.joblib")

    stored_path = tmp_path / "models" / "AAPL" / "trained_v2.joblib"
    assert artifact_uri == "models/AAPL/trained_v2.joblib"
    assert stored_path.read_bytes() == b"model-bytes"


def test_store_model_artifact_is_a_noop_when_already_under_model_root(tmp_path: Path, monkeypatch) -> None:
    _use_relative_model_root(monkeypatch, tmp_path)

    existing = tmp_path / "models"
    existing.mkdir()
    artifact = existing / "trained.joblib"
    artifact.write_bytes(b"model-bytes")

    artifact_uri = store_model_artifact(artifact)

    assert artifact_uri == "models/trained.joblib"
    assert artifact.read_bytes() == b"model-bytes"


def test_store_model_artifact_raises_for_missing_source(tmp_path: Path, monkeypatch) -> None:
    _use_relative_model_root(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="artifact_not_found"):
        store_model_artifact(tmp_path / "missing.joblib")
