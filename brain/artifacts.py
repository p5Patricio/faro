from __future__ import annotations

import os
import shutil
from pathlib import Path

MODEL_ARTIFACT_ROOT = Path(os.getenv("MODEL_ARTIFACT_DIR", "models"))


def resolve_model_artifact(artifact_uri: str, cache_dir: str | Path | None = None) -> Path:
    path = Path(artifact_uri)
    if path.exists():
        return path

    normalized_path = Path(artifact_uri.replace("\\", "/"))
    if normalized_path.exists():
        return normalized_path

    relative_to_root = MODEL_ARTIFACT_ROOT / normalized_path.name
    if relative_to_root.exists():
        return relative_to_root

    raise ValueError(f"artifact_not_found:{artifact_uri}")


def store_model_artifact(local_path: str | Path, object_path: str | None = None) -> str:
    source = Path(local_path)
    if not source.exists():
        raise ValueError(f"artifact_not_found:{source}")

    relative_target = Path((object_path or source.name).replace("\\", "/").strip("/"))
    target = MODEL_ARTIFACT_ROOT / relative_target
    target.parent.mkdir(parents=True, exist_ok=True)

    if source.resolve() != target.resolve():
        shutil.copy2(source, target)

    return target.as_posix()
