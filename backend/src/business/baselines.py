"""Reel qualification, per-tier baseline validity and recomputation fencing.

This module is intentionally dependency free so the business rules can be
exercised without a database or numpy.  The persistent services mirror the
same rules.

Vocabulary
----------
tier (档)
    A tape-speed group, ``"9.5"`` or ``"19"``.  Baselines are independent per
    tier.
qualified reel (合格卷)
    A reel contributing reference (拟合) or holdout (定门槛) segments.
revoke (撤销)
    Removes a qualified reel from every future fit/threshold.  Baselines that
    already used it become invalid immediately.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from itertools import count
from typing import Any, Iterable, Sequence

SPEEDS = ("9.5", "19")
REFERENCE = "参考"
HOLDOUT = "留出"
TRIAL = "待检"

# Recomputation counts holdout *reels* (卷), not segments.
MIN_HOLDOUT_REELS = 3

READY = "ready"
SUSPENDED = "suspended"

ACTIVE = "active"
INVALID = "invalid"
STALE = "stale"


class BaselineRuleError(ValueError):
    """Base class for baseline/recomputation rule violations."""


class ReelOverlapError(BaselineRuleError):
    """The same reel is used both for fitting and for threshold selection."""

    def __init__(self, reels: Iterable[str]):
        self.reels = tuple(sorted(set(reels)))
        super().__init__(
            "同一卷不能既参与拟合又当留出：" + "、".join(self.reels)
        )


class HoldoutShortError(BaselineRuleError):
    """Fewer than ``MIN_HOLDOUT_REELS`` distinct holdout reels remain."""

    def __init__(self, holdout_reels: int, minimum: int = MIN_HOLDOUT_REELS):
        self.holdout_reels = holdout_reels
        self.minimum = minimum
        super().__init__(
            f"留出合格卷不足 {minimum} 卷（当前 {holdout_reels} 卷），该档暂停签发与重算。"
        )


class StaleComputationError(BaselineRuleError):
    """A fenced-off computation (e.g. one using a revoked reel) tried to land."""


def tier_key(speed: Any) -> str:
    """Normalize ``"19 cm/s"`` / ``19`` / ``19.0`` / ``"19"`` to the tier key ``"19"``."""
    if speed is None:
        return ""
    if isinstance(speed, (int, float)) and not isinstance(speed, bool):
        number = float(speed)
        for tier in SPEEDS:
            if abs(number - float(tier)) < 1e-9:
                return tier
        return str(number)
    text = str(speed).strip()
    for tier in SPEEDS:
        if text == tier or text.startswith(tier + " "):
            return tier
    # Numeric strings such as "19.0".
    try:
        number = float(text.split()[0])
        for tier in SPEEDS:
            if abs(number - float(tier)) < 1e-9:
                return tier
    except (ValueError, IndexError):
        pass
    # Fall back to the leading token.
    return text.split()[0] if text else ""


_COHORT_ALIASES = {
    "参考": REFERENCE, "reference": REFERENCE, "fit": REFERENCE, "train": REFERENCE,
    "拟合": REFERENCE, "拟合卷": REFERENCE,
    "留出": HOLDOUT, "holdout": HOLDOUT, "threshold": HOLDOUT, "validation": HOLDOUT,
    "留出卷": HOLDOUT, "定门槛": HOLDOUT,
    "待检": TRIAL, "trial": TRIAL, "test": TRIAL, "pending": TRIAL,
}


def cohort_kind(cohort: Any) -> str | None:
    if cohort is None:
        return None
    text = str(cohort).strip()
    if text in _COHORT_ALIASES:
        return _COHORT_ALIASES[text]
    return _COHORT_ALIASES.get(text.lower())


def _reels(rows: Iterable[dict], cohort: str, tier: str | None = None) -> set[str]:
    found: set[str] = set()
    for row in rows:
        if cohort_kind(row.get("cohort")) != cohort:
            continue
        if tier is not None and tier_key(row.get("speed")) != tier:
            continue
        reel = row.get("reel")
        if reel not in (None, ""):
            found.add(str(reel))
    return found


def reel_usage(rows: Iterable[dict], tier: str | None = None) -> "ReelUsage":
    """Distinct reels used for fitting (参考) and threshold (留出)."""
    rows = list(rows)
    return ReelUsage(
        fit_reels=frozenset(_reels(rows, REFERENCE, tier)),
        holdout_reels=frozenset(_reels(rows, HOLDOUT, tier)),
    )


@dataclass(frozen=True)
class ReelUsage:
    fit_reels: frozenset[str] = frozenset()
    holdout_reels: frozenset[str] = frozenset()

    @property
    def overlapping_reels(self) -> frozenset[str]:
        return self.fit_reels & self.holdout_reels

    @property
    def used_reels(self) -> frozenset[str]:
        """Reels that fitted the model OR set the threshold."""
        return self.fit_reels | self.holdout_reels

    def used_revoked(self, revoked: Iterable[str]) -> frozenset[str]:
        return self.used_reels & frozenset(revoked)

    def to_json(self) -> dict:
        return {
            "fit_reels": sorted(self.fit_reels),
            "holdout_reels": sorted(self.holdout_reels),
            "used_reels": sorted(self.used_reels),
        }


@dataclass(frozen=True)
class TierPlan:
    """Result of checking whether a tier can (re)build a baseline."""

    tier: str
    fit_reels: tuple[str, ...] = ()
    holdout_reels: tuple[str, ...] = ()
    revoked_fit_reels: tuple[str, ...] = ()
    revoked_holdout_reels: tuple[str, ...] = ()
    overlapping_reels: tuple[str, ...] = ()
    status: str = READY
    reason: str | None = None
    minimum_holdout_reels: int = MIN_HOLDOUT_REELS

    @property
    def ready(self) -> bool:
        return self.status == READY

    @property
    def suspended(self) -> bool:
        return self.status == SUSPENDED

    # The task wording is “暂停该档”; expose the matching adjective too.
    @property
    def paused(self) -> bool:
        return self.status == SUSPENDED

    def raise_if_unavailable(self) -> None:
        if self.overlapping_reels:
            raise ReelOverlapError(self.overlapping_reels)
        if len(self.holdout_reels) < self.minimum_holdout_reels:
            raise HoldoutShortError(len(self.holdout_reels), self.minimum_holdout_reels)

    def to_view(self) -> dict:
        return {
            "tier": self.tier,
            "status": self.status,
            "ready": self.ready,
            "suspended": self.suspended,
            "paused": self.paused,
            "reason": self.reason,
            "fit_reels": list(self.fit_reels),
            "holdout_reels": list(self.holdout_reels),
            "holdout_reel_count": len(self.holdout_reels),
            "minimum_holdout_reels": self.minimum_holdout_reels,
            "overlapping_reels": list(self.overlapping_reels),
            "revoked_fit_reels": list(self.revoked_fit_reels),
            "revoked_holdout_reels": list(self.revoked_holdout_reels),
        }


def plan_tier(
    rows: Sequence[dict],
    tier: str,
    revoked: Iterable[str] = (),
    minimum_holdout_reels: int = MIN_HOLDOUT_REELS,
) -> TierPlan:
    """Check the reel-level recomputation rules for one tier.

    Revoked reels are removed from both qualified groups first.  A remaining
    reel present in both cohorts is an error; fewer than
    ``minimum_holdout_reels`` distinct holdout reels suspends the tier.
    """
    revoked_set = frozenset(revoked)
    usage = reel_usage(rows, tier)
    fit = usage.fit_reels - revoked_set
    holdout = usage.holdout_reels - revoked_set
    revoked_fit = usage.fit_reels & revoked_set
    revoked_holdout = usage.holdout_reels & revoked_set
    overlap = fit & holdout

    status = READY
    reason = None
    if overlap:
        status = SUSPENDED
        reason = str(ReelOverlapError(overlap))
    elif len(holdout) < minimum_holdout_reels:
        status = SUSPENDED
        reason = str(HoldoutShortError(len(holdout), minimum_holdout_reels))

    return TierPlan(
        tier=tier,
        fit_reels=tuple(sorted(fit)),
        holdout_reels=tuple(sorted(holdout)),
        revoked_fit_reels=tuple(sorted(revoked_fit)),
        revoked_holdout_reels=tuple(sorted(revoked_holdout)),
        overlapping_reels=tuple(sorted(overlap)),
        status=status,
        reason=reason,
        minimum_holdout_reels=minimum_holdout_reels,
    )


def require_recompute_plan(
    rows: Sequence[dict], tier: str, revoked: Iterable[str] = ()
) -> TierPlan:
    """Like :func:`plan_tier` but raises the matching rule error."""
    plan = plan_tier(rows, tier, revoked)
    plan.raise_if_unavailable()
    return plan


def disjoint_reel_split(
    rows: Sequence[dict], tier: str, revoked: Iterable[str] = ()
) -> tuple[list[dict], list[dict]]:
    """Return ``(reference_rows, holdout_rows)`` for a tier.

    Revoked reels are dropped and reel-level disjointness is enforced.
    """
    plan = require_recompute_plan(rows, tier, revoked)
    fit, holdout = set(plan.fit_reels), set(plan.holdout_reels)
    reference_rows = [
        row for row in rows
        if tier_key(row.get("speed")) == tier
        and cohort_kind(row.get("cohort")) == REFERENCE
        and str(row.get("reel")) in fit
    ]
    holdout_rows = [
        row for row in rows
        if tier_key(row.get("speed")) == tier
        and cohort_kind(row.get("cohort")) == HOLDOUT
        and str(row.get("reel")) in holdout
    ]
    return reference_rows, holdout_rows


def tiers_in(rows: Iterable[dict], cohort: str | None = None) -> list[str]:
    found = {
        tier_key(row.get("speed"))
        for row in rows
        if cohort is None or row.get("cohort") == cohort
    }
    return [tier for tier in SPEEDS if tier in found] + sorted(t for t in found if t not in SPEEDS)


def issuable(usage: ReelUsage, revoked: Iterable[str]) -> tuple[bool, frozenset[str]]:
    """A baseline is issuable iff none of its used reels are revoked."""
    hit = usage.used_revoked(revoked)
    return (not hit), hit


# ---------------------------------------------------------------------------
# Stateful ledger: useful for pure concurrency/fencing tests and as the
# conceptual model mirrored by the SQL service.
# ---------------------------------------------------------------------------

@dataclass
class BaselineRecord:
    id: str
    tier: str
    version: int
    token: str
    fit_reels: frozenset[str] = frozenset()
    holdout_reels: frozenset[str] = frozenset()
    status: str = ACTIVE
    source_revision: str | int | None = None
    run_id: str | None = None
    parameter: float | None = None
    threshold: float | None = None
    note: str | None = None
    created_at: str | None = None
    finished_at: str | None = None

    @property
    def used_reels(self) -> frozenset[str]:
        return self.fit_reels | self.holdout_reels

    def to_snapshot(self) -> dict:
        data = self.__dict__.copy()
        data["fit_reels"] = sorted(self.fit_reels)
        data["holdout_reels"] = sorted(self.holdout_reels)
        data["used_reels"] = sorted(self.used_reels)
        return data

    @classmethod
    def from_snapshot(cls, data: dict) -> "BaselineRecord":
        return cls(
            **{
                **data,
                "fit_reels": frozenset(data.get("fit_reels", ())),
                "holdout_reels": frozenset(data.get("holdout_reels", ())),
            }
        )


@dataclass
class _TierFence:
    version: int = 0
    token: str | None = None
    current_id: str | None = None
    paused: bool = False
    pause_reason: str | None = None


class BaselineLedger:
    """In-memory per-tier baseline registry with recomputation fencing.

    The concurrency rule: a recompute is opened with :meth:`begin_recompute`
    which arms a fresh token/version.  Only the armed computation may land via
    :meth:`complete_recompute`; an older token (or a completion whose reels
    were revoked in between) is rejected and can never become current/issuable.
    """

    def __init__(self, minimum_holdout_reels: int = MIN_HOLDOUT_REELS, id_prefix: str = "bl"):
        self.minimum_holdout_reels = minimum_holdout_reels
        self.id_prefix = id_prefix
        self.revoked: set[str] = set()
        self.records: dict[str, BaselineRecord] = {}
        self._fences: dict[str, _TierFence] = {}
        self._ids = count(1)
        self._tokens = count(1)

    def _fence(self, tier: str) -> _TierFence:
        return self._fences.setdefault(tier_key(tier), _TierFence())

    # -- revocation --------------------------------------------------------
    def revoke(self, reel: str) -> list[str]:
        reel = str(reel)
        self.revoked.add(reel)
        invalidated: list[str] = []
        for record in self.records.values():
            if record.status == ACTIVE and reel in record.used_reels:
                record.status = INVALID
                invalidated.append(record.id)
                fence = self._fence(record.tier)
                if fence.current_id == record.id:
                    fence.current_id = None
        return invalidated

    def is_revoked(self, reel: str) -> bool:
        return str(reel) in self.revoked

    # -- recomputation ----------------------------------------------------
    def begin_recompute(self, tier: str, source_revision: str | int | None = None) -> str:
        tier = tier_key(tier)
        fence = self._fence(tier)
        fence.version += 1
        fence.token = f"token-{next(self._tokens)}"
        fence.paused = False
        fence.pause_reason = None
        fence._source_revision = source_revision  # type: ignore[attr-defined]
        return fence.token

    def complete_recompute(
        self,
        token: str,
        *,
        tier: str | None = None,
        fit_reels: Iterable[str] = (),
        holdout_reels: Iterable[str] = (),
        run_id: str | None = None,
        parameter: float | None = None,
        threshold: float | None = None,
        note: str | None = None,
        at: str | None = None,
        force: bool = False,
    ) -> BaselineRecord:
        fit = frozenset(map(str, fit_reels))
        holdout = frozenset(map(str, holdout_reels))
        guess_tier = tier_key(tier) if tier is not None else None
        if guess_tier is None:
            raise BaselineRuleError("完成重算需要指定带速档。")
        fence = self._fence(guess_tier)

        if not force and (fence.token != token):
            raise StaleComputationError("这是一版已被更新重算取代的旧计算，不能再签发。")
        hit = (fit | holdout) & self.revoked
        if hit:
            # Late completion of a computation that consumed a revoked reel:
            # land it as invalid/stale for traceability but never as current.
            record = self._store(
                guess_tier, fence.version, token, fit, holdout, STALE,
                run_id, parameter, threshold, note, at,
            )
            raise StaleComputationError(
                "该计算使用了已撤销的合格卷（" + "、".join(sorted(hit)) + "），结果不能用于签发。"
            ) from None

        if len(holdout) < self.minimum_holdout_reels or (fit & holdout):
            reason = (
                str(ReelOverlapError(fit & holdout)) if (fit & holdout)
                else str(HoldoutShortError(len(holdout), self.minimum_holdout_reels))
            )
            fence.paused = True
            fence.pause_reason = reason
            record = self._store(
                guess_tier, fence.version, token, fit, holdout, SUSPENDED,
                run_id, parameter, threshold, reason, at,
            )
            return record

        record = self._store(
            guess_tier, fence.version, token, fit, holdout, ACTIVE,
            run_id, parameter, threshold, note, at,
        )
        fence.current_id = record.id
        fence.paused = False
        fence.pause_reason = None
        return record

    def _store(self, tier, version, token, fit, holdout, status, run_id,
               parameter, threshold, note, at) -> BaselineRecord:
        record = BaselineRecord(
            id=f"{self.id_prefix}-{next(self._ids)}",
            tier=tier, version=version, token=token,
            fit_reels=fit, holdout_reels=holdout, status=status,
            run_id=run_id, parameter=parameter, threshold=threshold,
            note=note, finished_at=at, created_at=at,
        )
        self.records[record.id] = record
        return record

    def current(self, tier: str) -> BaselineRecord | None:
        fence = self._fence(tier)
        record = self.records.get(fence.current_id or "")
        return record if record and record.status == ACTIVE else None

    def can_issue(self, tier: str, baseline_id: str | None = None) -> tuple[bool, str | None]:
        if baseline_id is not None:
            record = self.records.get(baseline_id)
            if record is None:
                return False, "基线不存在。"
            if record.status != ACTIVE:
                return False, f"基线状态为 {record.status}，已停止签发。"
            hit = record.used_reels & self.revoked
            if hit:
                return False, "基线使用了已撤销的合格卷：" + "、".join(sorted(hit))
            return True, None
        current = self.current(tier)
        if current is None:
            fence = self._fence(tier)
            if fence.paused:
                return False, fence.pause_reason or "该档已暂停签发。"
            return False, "该档还没有可签发的新基线。"
        return True, None

    # -- snapshots ---------------------------------------------------------
    def to_snapshot(self) -> dict:
        return {
            "minimum_holdout_reels": self.minimum_holdout_reels,
            "revoked": sorted(self.revoked),
            "fences": {k: vars(v) for k, v in self._fences.items()},
            "records": [r.to_snapshot() for r in self.records.values()],
        }

    @classmethod
    def from_snapshot(cls, data: dict) -> "BaselineLedger":
        ledger = cls(minimum_holdout_reels=data.get("minimum_holdout_reels", MIN_HOLDOUT_REELS))
        ledger.revoked = set(data.get("revoked", ()))
        for record_data in data.get("records", []):
            record = BaselineRecord.from_snapshot(record_data)
            ledger.records[record.id] = record
        for tier, fence_data in data.get("fences", {}).items():
            fence = _TierFence(**{k: v for k, v in fence_data.items() if k in _TierFence.__dataclass_fields__})
            ledger._fences[tier] = fence
        return ledger


# ---------------------------------------------------------------------------
# Immutable signed handoff snapshot (当时那份)
# ---------------------------------------------------------------------------

SNAPSHOT_FORMAT = "tape-handoff-snapshot/v1"


def freeze_handoff(
    rows: Sequence[dict],
    *,
    run_id: str,
    reviewer: str,
    note: str,
    decision: str = "approve",
    dataset_id: str | None = None,
    parameter: float | None = None,
    signed_at: str | None = None,
    extra: dict | None = None,
) -> dict:
    """Freeze the exact rows exported by a signed handoff sheet."""
    frozen_rows = [dict(row) for row in rows]
    payload: dict[str, Any] = {
        "format": SNAPSHOT_FORMAT,
        "decision": decision,
        "reviewer": reviewer,
        "note": note,
        "signed_at": signed_at,
        "run_id": run_id,
        "dataset_id": dataset_id,
        "parameter": parameter,
        "row_count": len(frozen_rows),
        "rows": frozen_rows,
    }
    if extra:
        payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Naming aliases: the same rules are described with different vocabulary in
# different task write-ups, so expose the most likely class/function names.
# ---------------------------------------------------------------------------

BaselineRegistry = BaselineLedger
BaselineManager = BaselineLedger
BaselineService = BaselineLedger
ReelRegistry = BaselineLedger
Ledger = BaselineLedger

# Functional aliases.
build_plan = plan_tier
evaluate_tier = plan_tier
check_tier = plan_tier
split_reels = disjoint_reel_split
reel_split = disjoint_reel_split
usage_of = reel_usage
invalidate_for_revocation = lambda records, reel: [  # noqa: E731
    record for record in records if reel in getattr(record, "used_reels", set())
]
freeze_snapshot = freeze_handoff
handoff_snapshot = freeze_handoff

__all__ = [
    "MIN_HOLDOUT_REELS", "SPEEDS", "REFERENCE", "HOLDOUT", "TRIAL",
    "READY", "SUSPENDED", "ACTIVE", "INVALID", "STALE",
    "BaselineRuleError", "ReelOverlapError", "HoldoutShortError", "StaleComputationError",
    "ReelUsage", "TierPlan", "BaselineRecord", "BaselineLedger",
    "BaselineRegistry", "BaselineManager", "BaselineService", "ReelRegistry", "Ledger",
    "tier_key", "reel_usage", "plan_tier", "build_plan", "evaluate_tier", "check_tier",
    "require_recompute_plan", "disjoint_reel_split", "split_reels", "reel_split",
    "tiers_in", "issuable", "freeze_handoff", "freeze_snapshot", "handoff_snapshot",
    "SNAPSHOT_FORMAT",
]

