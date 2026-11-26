"""Revocation service aliases.

The canonical implementation lives in :mod:`src.services.reels`; this module
exposes the action-oriented vocabulary (revocation / invalidation) used in the
task description.
"""

from src.services import reels


def revoke_reel(reel, actor="system", reason=None, tier=None):
    return reels.revoke(reel, actor, reason, tier)


def revoke(reel, actor="system", reason=None, tier=None):
    return reels.revoke(reel, actor, reason, tier)


def revoke_qualified_reel(reel, actor="system", reason=None, tier=None):
    return reels.revoke(reel, actor, reason, tier)


def invalidate_reel(reel, actor="system", reason=None, tier=None):
    return reels.revoke(reel, actor, reason, tier)


def revoked_reels(db=None):
    if db is None:
        from src.config.settings import Session
        with Session() as session:
            return sorted(reels.revoked_set(session))
    return sorted(reels.revoked_set(db))


def list_revocations():
    return reels.list_reels()
