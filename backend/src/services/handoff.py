"""Signed handoff snapshot helpers (当时那份).

The FastAPI export route uses these indirectly; this module exposes the
snapshot/restore vocabulary directly for non-HTTP callers.
"""

from src.business.baselines import SNAPSHOT_FORMAT, freeze_handoff  # noqa: F401


def freeze_signed_rows(rows, *, run_id, reviewer, note, **kwargs):
    return freeze_handoff(
        rows, run_id=run_id, reviewer=reviewer, note=note,
        decision=kwargs.pop("decision", "approve"), **kwargs
    )


def snapshot_rows(review, run=None):
    """Return the frozen rows for a signed review.

    Prefers the snapshot frozen at sign time; falls back to filtering the
    (immutable) run result for records created before snapshots existed.
    """
    snapshot = getattr(review, "snapshot", None)
    if snapshot and snapshot.get("rows"):
        return snapshot["rows"]
    selected = set(review.samples or [])
    result_rows = ((run.result if run is not None else None) or {}).get("rows", [])
    return [row for row in result_rows if row.get("sample_id") in selected]


def is_frozen(snapshot) -> bool:
    return isinstance(snapshot, dict) and snapshot.get("format") == SNAPSHOT_FORMAT
