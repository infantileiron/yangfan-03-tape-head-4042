"""Qualified-reel registry and revocation-driven baseline invalidation."""

from fastapi import HTTPException
from sqlalchemy import select

from src.business.baselines import reel_usage, tier_key
from src.config.settings import Session
from src.constants.workflow import BaselineStatus
from src.models.baseline import Baseline
from src.models.dataset import Dataset
from src.models.reel import RevokedReel
from src.schemas.resources import reel_view
from src.services.audit import record


def revoked_set(db) -> set[str]:
    return set(db.scalars(select(RevokedReel.reel)).all())


def is_revoked(db, reel: str) -> bool:
    return db.get(RevokedReel, str(reel)) is not None


def _derive_reel_index(db) -> dict[str, dict]:
    """Summarise every reel seen in source datasets (tier/cohorts)."""
    index: dict[str, dict] = {}
    datasets = db.scalars(select(Dataset)).all()
    for dataset in datasets:
        for row in dataset.rows or []:
            reel = row.get("reel")
            if not reel:
                continue
            item = index.setdefault(reel, {
                "reel": reel, "tiers": set(), "cohorts": set(),
                "dataset_ids": set(), "sample_count": 0,
            })
            item["tiers"].add(tier_key(row.get("speed")))
            item["cohorts"].add(row.get("cohort"))
            item["dataset_ids"].add(dataset.id)
            item["sample_count"] += 1
    return index


def list_reels():
    with Session() as db:
        revoked = {item.reel: item for item in db.scalars(select(RevokedReel)).all()}
        index = _derive_reel_index(db)
        reels = set(revoked) | set(index)
        items = []
        for reel in sorted(reels):
            model = revoked.get(reel)
            derived = None
            if reel in index:
                info = index[reel]
                derived = {
                    "tier": model.tier if model else (sorted(t for t in info["tiers"] if t)[0] if info["tiers"] else None),
                    "tiers": sorted(t for t in info["tiers"] if t),
                    "cohorts": sorted(c for c in info["cohorts"] if c),
                    "dataset_ids": sorted(info["dataset_ids"]),
                    "sample_count": info["sample_count"],
                    "qualified": "参考" in info["cohorts"] or "留出" in info["cohorts"],
                }
            if model is not None:
                items.append(reel_view(model, derived))
            else:
                items.append({
                    "reel": reel, "status": "qualified", "actor": None,
                    "reason": None, "revoked_at": None, **(derived or {}),
                })
        return items


def revoke(reel: str, actor: str, reason: str | None = None, tier: str | None = None):
    reel = str(reel).strip()
    with Session.begin() as db:
        existing = db.get(RevokedReel, reel)
        if existing is not None:
            # Idempotent: a repeated revocation still reports the same effect.
            invalidated = [
                b.id for b in db.scalars(select(Baseline).where(Baseline.status == BaselineStatus.INVALID.value))
                if reel in (b.used_reels or [])
            ]
            return {"reel": reel, "already_revoked": True, "invalidated_baseline_ids": invalidated}

        if tier is None:
            # Best-effort tier discovery from the latest source rows.
            for dataset in db.scalars(select(Dataset).order_by(Dataset.created_at.desc())).all():
                match = next((r for r in dataset.rows or [] if r.get("reel") == reel), None)
                if match:
                    tier = tier_key(match.get("speed")) or None
                    break

        entry = RevokedReel(reel=reel, tier=tier, reason=reason, actor=actor)
        db.add(entry)

        # Immediate invalidation: every baseline that fitted on this reel or
        # used it to set the threshold dies with the source-data update.
        invalidated_ids: list[str] = []
        baselines = db.scalars(select(Baseline).where(Baseline.status == BaselineStatus.ACTIVE.value)).all()
        for baseline in baselines:
            if reel in (baseline.used_reels or []):
                baseline.status = BaselineStatus.INVALID.value
                invalidated_ids.append(baseline.id)

        record(db, actor, "reel_revoked", reel)
        for baseline_id in invalidated_ids:
            record(db, actor, "baseline_invalidated", baseline_id)

        return {
            **reel_view(entry),
            "already_revoked": False,
            "invalidated_baseline_ids": invalidated_ids,
        }


def usage_for_dataset(db, dataset: Dataset) -> dict[str, object]:
    """Convenience helper returning per-tier :class:`ReelUsage`."""
    rows = dataset.rows or []
    return {tier: reel_usage(rows, tier) for tier in {tier_key(r.get("speed")) for r in rows}}
