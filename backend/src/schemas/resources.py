from datetime import datetime, timezone


def utc(value: datetime | None):
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def dataset_view(dataset, include_rows=False):
    item = {
        "id": dataset.id, "name": dataset.name, "count": len(dataset.rows),
        "checksum": dataset.checksum, "author": dataset.author, "created_at": utc(dataset.created_at),
    }
    if include_rows:
        item["rows"] = dataset.rows
    return item


def run_view(run, include_result=False):
    item = {
        "id": run.id, "dataset_id": run.dataset_id, "label": run.label, "parameter": run.parameter,
        "status": run.status, "error": run.error, "actor": run.actor,
        "created_at": utc(run.created_at), "started_at": utc(run.started_at),
        "finished_at": utc(run.finished_at),
    }
    if include_result:
        item["result"] = run.result
    return item


def review_view(review):
    snapshot = getattr(review, "snapshot", None)
    return {
        "id": review.id, "run_id": review.run_id, "decision": review.decision,
        "samples": review.samples, "note": review.note, "reviewer": review.reviewer,
        "snapshot": snapshot,
        "has_snapshot": bool(snapshot),
        "created_at": utc(review.created_at),
    }


def reel_view(reel, derived=None):
    item = {
        "reel": reel.reel,
        "tier": reel.tier,
        "status": "revoked",
        "reason": reel.reason,
        "actor": reel.actor,
        "revoked_at": utc(reel.created_at),
    }
    if derived:
        item.update(derived)
    return item


def baseline_view(baseline):
    status = baseline.status
    return {
        "id": baseline.id,
        "tier": baseline.tier,
        "status": status,
        "state": status,
        "active": status == "active",
        "invalid": status == "invalid",
        "stale": status == "stale",
        "suspended": status == "suspended",
        "paused": status == "suspended",
        "generation": baseline.generation,
        "fence": baseline.fence,
        "run_id": baseline.run_id,
        "dataset_id": baseline.dataset_id,
        "source_checksum": baseline.source_checksum,
        "parameter": baseline.parameter,
        "threshold": baseline.threshold,
        "note": baseline.note,
        "fit_reels": list(baseline.fit_reels or []),
        "holdout_reels": list(baseline.holdout_reels or []),
        "used_reels": list(baseline.used_reels or []),
        "detail": baseline.detail,
        "actor": baseline.actor,
        "created_at": utc(baseline.created_at),
        "finished_at": utc(baseline.finished_at),
    }


def audit_view(event):
    return {"actor": event.actor, "action": event.action, "subject": event.subject, "created_at": utc(event.created_at)}
