from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class UniverseDocument:
    index: str
    snapshot_date: str
    source: str
    membership_bias: str
    defaults: dict[str, Any]
    members: tuple[dict[str, str], ...]


def load_universe_document(path: str | Path) -> UniverseDocument:
    """Load a universe snapshot document (e.g. ``config/universe.sp100.json``).

    Fails at load time -- never at report time -- when ``snapshot_date`` or
    ``membership_bias`` is missing or blank, so a malformed snapshot can never
    silently produce disclosure-bearing output without its caveat.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    snapshot_date = raw.get("snapshot_date")
    if not snapshot_date or not str(snapshot_date).strip():
        raise ValueError("universe document is missing a non-blank 'snapshot_date'")

    membership_bias = raw.get("membership_bias")
    if not membership_bias or not str(membership_bias).strip():
        raise ValueError("universe document is missing a non-blank 'membership_bias'")

    return UniverseDocument(
        index=raw["index"],
        snapshot_date=snapshot_date,
        source=raw["source"],
        membership_bias=membership_bias,
        defaults=raw.get("defaults", {}),
        members=tuple(raw.get("members", [])),
    )


def universe_disclosure(doc: UniverseDocument) -> dict[str, Any]:
    """Build the survivorship-bias disclosure block for reports/API surfaces."""
    return {
        "index": doc.index,
        "snapshot_date": doc.snapshot_date,
        "source": doc.source,
        "membership_bias": doc.membership_bias,
        "member_count": len(doc.members),
    }


def universe_report_block(doc: UniverseDocument | None) -> dict[str, Any]:
    """Build the `"universe"` key for a report/API payload. Never omits the
    key: with no document available, emits an explicit incomplete-disclosure
    marker instead of silently dropping the survivorship-bias caveat."""
    if doc is None:
        return {"universe": {"disclosure_status": "incomplete", "reason": "no_universe_snapshot"}}
    return {"universe": universe_disclosure(doc)}
