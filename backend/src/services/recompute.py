"""Recompute entry points and aliases for the baseline lifecycle."""

from types import SimpleNamespace

from src.services import baselines


def _as_body(dataset_id, parameter=None, label=None, tiers=None, sync=True):
    return SimpleNamespace(
        dataset_id=dataset_id,
        parameter=parameter,
        label=label,
        tiers=tiers,
        sync=sync,
    )


def recompute(dataset_id, actor="system", parameter=None, label=None, tiers=None):
    """Synchronously recompute per-tier baselines for a dataset."""
    return baselines.recompute_now(_as_body(dataset_id, parameter, label, tiers), actor)


def recompute_baselines(dataset_id, actor="system", parameter=None, tiers=None):
    return recompute(dataset_id, actor=actor, parameter=parameter, tiers=tiers)


def recompute_tiers(dataset_id, tiers, actor="system", parameter=None):
    return recompute(dataset_id, actor=actor, parameter=parameter, tiers=list(tiers))


def plan(dataset_id):
    return baselines.plan_for_dataset(dataset_id)


def list_baselines(tier=None, dataset_id=None):
    return baselines.list_baselines(tier=tier, dataset_id=dataset_id)
