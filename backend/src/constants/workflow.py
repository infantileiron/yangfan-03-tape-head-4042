from enum import Enum


class Role(str, Enum):
    ANALYST = "analyst"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class Stage(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Decision(str, Enum):
    APPROVE = "approve"
    HOLD = "hold"


class ReelStatus(str, Enum):
    """Qualification state of a source reel (合格卷)."""

    QUALIFIED = "qualified"
    REVOKED = "revoked"


class BaselineStatus(str, Enum):
    """Lifecycle of a per-speed (档) calibration baseline."""

    ACTIVE = "active"          # current, clean and issuable
    INVALID = "invalid"        # used a reel that has since been revoked
    SUSPENDED = "suspended"    # recompute cannot qualify the tier (e.g. <3 holdout reels)
    STALE = "stale"            # fenced out by a newer recomputation / late completion


# Issuance gate outcomes used in API responses and audit entries.
class Issuance(str, Enum):
    OPEN = "open"              # a valid baseline exists, signing allowed
    BLOCKED = "blocked"        # baseline invalid / stale / suspended
    PAUSED = "paused"          # tier has no fresh baseline after a short-holdout recompute
