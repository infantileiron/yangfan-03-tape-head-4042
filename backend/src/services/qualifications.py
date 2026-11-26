"""Qualification vocabulary alias over :mod:`src.services.reels`."""

from src.services.reels import (  # noqa: F401
    is_revoked,
    list_reels as list_qualifications,
    revoke,
    revoked_set,
    usage_for_dataset,
)


def revoke_qualification(reel, actor="system", reason=None, tier=None):
    return revoke(reel, actor, reason, tier)
