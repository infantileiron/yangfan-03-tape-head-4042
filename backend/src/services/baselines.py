"""Baseline lifecycle: recording after calculations, issuance gate, recompute."""

from fastapi import HTTPException
from sqlalchemy import select

from src.business.algorithm import recompute_tier
from src.business.baselines import (
    ACTIVE,
    INVALID,
    MIN_HOLDOUT_REELS,
    SUSPENDED,
    SPEEDS,
    tier_key,
    plan_tier,
)
from src.business.profile import PROFILE
from src.config.settings import ARTIFACTS, Session
from src.constants.workflow import BaselineStatus
from src.models.baseline import Baseline
from src.models.dataset import Dataset
from src.models.run import Run
from src.models.base import new_id, utcnow
from src.schemas.resources import baseline_view, run_view
from src.services import reels
from src.services.audit import record
from src.utils.csv_data import render_csv


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def list_baselines(tier: str | None = None, dataset_id: str | None = None):
    with Session() as db:
        stmt = select(Baseline).order_by(Baseline.created_at.desc(), Baseline.id.desc())
        if tier:
            stmt = stmt.where(Baseline.tier == tier_key(tier))
        if dataset_id:
            stmt = stmt.where(Baseline.dataset_id == dataset_id)
        items = [baseline_view(row) for row in db.scalars(stmt)]
    return _annotate_current(items)


def can_issue_baseline(baseline_id: str) -> tuple[bool, str | None]:
    """DB-backed issuance check for one baseline id."""
    with Session() as db:
        baseline = db.get(Baseline, baseline_id)
        if baseline is None:
            return False, "基线不存在。"
        if baseline.status != BaselineStatus.ACTIVE.value:
            return False, _STATUS_MESSAGE.get(baseline.status, "该档基线当前不可签发。")
        hit = set(baseline.used_reels or []) & reels.revoked_set(db)
        if hit:
            return False, "基线使用了已撤销的合格卷：" + "、".join(sorted(hit))
        return True, None


def get_baseline(baseline_id: str):
    with Session() as db:
        baseline = db.get(Baseline, baseline_id)
        if baseline is None:
            raise HTTPException(404, "基线不存在。")
        view = baseline_view(baseline)
        hit = set(baseline.used_reels or []) & reels.revoked_set(db)
        issuable = baseline.status == BaselineStatus.ACTIVE.value and not hit
        reason = None
        if not issuable:
            reason = (
                ("基线使用了已撤销的合格卷：" + "、".join(sorted(hit))) if hit
                else _STATUS_MESSAGE.get(baseline.status, "该档基线当前不可签发。")
            )
        view["issuable"] = issuable
        view["reason"] = reason
        return view


def _annotate_current(items: list[dict]) -> list[dict]:
    current_by_tier: dict[str, str] = {}
    for item in reversed(items):  # oldest first, newest wins
        if item["status"] == BaselineStatus.ACTIVE.value:
            current_by_tier[item["tier"]] = item["id"]
    for item in items:
        item["is_current"] = current_by_tier.get(item["tier"]) == item["id"]
        item["issuable"] = item["status"] == BaselineStatus.ACTIVE.value
    return items


def plan_for_dataset(dataset_id: str):
    with Session() as db:
        dataset = db.get(Dataset, dataset_id)
        if dataset is None:
            raise HTTPException(404, "数据版本不存在。")
        revoked = reels.revoked_set(db)
        rows = dataset.rows or []
        tiers = sorted({tier_key(r.get("speed")) for r in rows if r.get("cohort") in ("参考", "留出")})
        plans = [plan_tier(rows, tier, revoked).to_view() for tier in tiers]
        return {"dataset_id": dataset_id, "minimum_holdout_reels": MIN_HOLDOUT_REELS, "tiers": plans}


def issuance_summary(db, run: Run) -> dict:
    """Per-tier issuable state for a run, used by the run-details API."""
    revoked = reels.revoked_set(db)
    rows = list(db.scalars(select(Baseline).where(Baseline.run_id == run.id)))
    tiers: dict[str, dict] = {}
    for baseline in rows:
        hit = set(baseline.used_reels or []) & revoked
        issuable = baseline.status == BaselineStatus.ACTIVE.value and not hit
        reason = None
        if not issuable:
            reason = (
                ("使用已撤销卷：" + "、".join(sorted(hit))) if hit
                else _STATUS_MESSAGE.get(baseline.status, "该档基线当前不可签发。")
            )
        tiers[baseline.tier] = {
            "status": baseline.status,
            "issuable": issuable,
            "reason": reason,
            "baseline_id": baseline.id,
        }
    if not tiers:
        # Legacy/unrecorded run: still answer from source-reel revocation.
        dataset = db.get(Dataset, run.dataset_id)
        if dataset is not None and run.result:
            for result_row in run.result.get("rows", []):
                tier = tier_key(result_row.get("tier") or result_row.get("speed"))
                if not tier or tier in tiers:
                    continue
                usage = _usage_from_rows(dataset.rows or [], tier)
                hit = usage.used_reels & revoked
                tiers[tier] = {
                    "status": BaselineStatus.ACTIVE.value if not hit else BaselineStatus.INVALID.value,
                    "issuable": not hit,
                    "reason": ("使用已撤销卷：" + "、".join(sorted(hit))) if hit else None,
                    "baseline_id": None,
                }
    all_issuable = all(item["issuable"] for item in tiers.values()) if tiers else True
    return {"issuable": all_issuable, "tiers": tiers, "revoked_reels": sorted(revoked)}


# ---------------------------------------------------------------------------
# Recording after a run
# ---------------------------------------------------------------------------

def sync_for_run(db, run: Run, job_rows: list[dict] | None = None) -> list[Baseline]:
    """Create/update per-tier baseline rows from a succeeded run.

    Must be called inside the transaction that marks the run succeeded, after
    the calculation finished, so the revocation set read here is fresh.  Usage
    is taken from ``job_rows`` -- the rows the calculation *actually* consumed
    -- which is what makes a late stale job fence correctly.  When omitted the
    source dataset rows are used.
    """
    dataset = db.get(Dataset, run.dataset_id)
    source_rows = job_rows if job_rows is not None else ((dataset.rows if dataset else []) or [])
    revoked = reels.revoked_set(db)

    tiers = {tier_key(r.get("speed")) for r in source_rows if r.get("cohort") in ("参考", "留出")}
    tiers.update(tier_key(r.get("speed")) for r in ((dataset.rows if dataset else []) or [])
                 if r.get("cohort") in ("参考", "留出"))
    tiers = {t for t in tiers if t}

    saved: list[Baseline] = []
    for tier in sorted(tiers):
        usage = _usage_from_rows(source_rows, tier)
        fit, holdout = set(usage.fit_reels), set(usage.holdout_reels)
        used = fit | holdout
        consumed_revoked = used & revoked
        overlap = fit & holdout

        if consumed_revoked:
            status = BaselineStatus.INVALID.value
            note = "基线使用了已撤销的合格卷：" + "、".join(sorted(consumed_revoked))
        elif overlap:
            status = BaselineStatus.SUSPENDED.value
            note = "同一卷不能既参与拟合又当留出：" + "、".join(sorted(overlap))
        elif len(holdout) < MIN_HOLDOUT_REELS:
            status = BaselineStatus.SUSPENDED.value
            note = f"留出合格卷不足 {MIN_HOLDOUT_REELS} 卷（当前 {len(holdout)} 卷），该档暂停。"
        else:
            status = BaselineStatus.ACTIVE.value
            note = None

        existing = db.scalar(select(Baseline).where(
            Baseline.run_id == run.id, Baseline.tier == tier
        ))
        baseline = existing or Baseline(id=new_id(), run_id=run.id)
        baseline.tier = tier
        baseline.status = status
        baseline.dataset_id = run.dataset_id
        baseline.source_checksum = dataset.checksum if dataset else None
        baseline.parameter = run.parameter
        baseline.fence = run.lease or run.id
        baseline.fit_reels = sorted(fit)
        baseline.holdout_reels = sorted(holdout)
        baseline.used_reels = sorted(used)
        baseline.note = note
        baseline.finished_at = utcnow()
        if existing is None:
            prior = db.scalars(select(Baseline).where(Baseline.tier == tier)).all()
            baseline.generation = (max((b.generation or 0) for b in prior) + 1) if prior else 1
            baseline.actor = run.actor
            db.add(baseline)
        saved.append(baseline)
    db.flush()
    return saved


def _usage_from_rows(rows, tier):
    from src.business.baselines import reel_usage
    return reel_usage(rows, tier)


# ---------------------------------------------------------------------------
# Issuance gate used by reviews.sign
# ---------------------------------------------------------------------------

_STATUS_MESSAGE = {
    BaselineStatus.INVALID.value: "该档基线因合格卷被撤销而已失效，请用当前合格卷重算后再签发。",
    BaselineStatus.SUSPENDED.value: "该档留出合格卷不足三卷（或拟合/留出卷重叠），已暂停签发，请补卷并重算。",
    BaselineStatus.STALE.value: "这版计算已被更新的重算取代（或使用了撤销卷），不能用于签发。",
}


def assert_run_signable(db, run: Run, sample_ids) -> list[str]:
    """Validate that every selected sample's tier has a clean current baseline.

    Returns the affected tiers.  Raises 409 with an actionable Chinese message
    otherwise.  Already-signed handoffs never call this on export.
    """
    if not sample_ids:
        return []
    result_rows = (run.result or {}).get("rows", [])
    selected = set(sample_ids)
    selected_rows = [row for row in result_rows if row.get("sample_id") in selected]
    tiers = {tier_key(row.get("tier") or row.get("speed")) for row in selected_rows}
    tiers.discard("")

    revoked = reels.revoked_set(db)
    for tier in sorted(tiers):
        baseline = db.scalar(
            select(Baseline)
            .where(Baseline.run_id == run.id, Baseline.tier == tier)
            .with_for_update()
        )
        if baseline is not None:
            if baseline.status != BaselineStatus.ACTIVE.value:
                raise HTTPException(409, f"{tier} cm/s 档：{_STATUS_MESSAGE.get(baseline.status, '该档基线当前不可签发。')}")
            hit = set(baseline.used_reels or []) & revoked
            if hit:
                # Defensive: revocation normally flips status immediately.
                baseline.status = BaselineStatus.INVALID.value
                raise HTTPException(409, f"{tier} cm/s 档基线使用了已撤销的合格卷（{'、'.join(sorted(hit))}），已失效并停止签发。")
            continue

        # Backward-compatible fallback for runs without Baseline bookkeeping:
        # derive reel usage straight from the source dataset.
        dataset = db.get(Dataset, run.dataset_id)
        if dataset is None:
            continue
        usage = _usage_from_rows(dataset.rows or [], tier)
        hit = usage.used_reels & revoked
        if hit:
            raise HTTPException(409, f"{tier} cm/s 档计算使用了已撤销的合格卷（{'、'.join(sorted(hit))}），不能签发，请重算。")
    return sorted(tiers)


# ---------------------------------------------------------------------------
# Recompute (synchronous, per-tier tolerant)
# ---------------------------------------------------------------------------

def recompute_now(body, actor: str):
    parameter = body.parameter if body.parameter is not None else PROFILE["parameter"]["default"]
    control = PROFILE["parameter"]
    if not control["min"] <= parameter <= control["max"]:
        raise HTTPException(422, f"「{control['label']}」超出允许范围。")

    with Session.begin() as db:
        dataset = db.get(Dataset, body.dataset_id)
        if dataset is None:
            raise HTTPException(404, "数据版本不存在。")
        rows = dataset.rows or []
        revoked = reels.revoked_set(db)

        wanted = {tier_key(t) for t in (body.tiers or []) if tier_key(t)} or set(SPEEDS)
        tiers = sorted({
            tier_key(r.get("speed")) for r in rows
            if r.get("cohort") in ("参考", "留出") and tier_key(r.get("speed")) in wanted
        })

        combined_rows: list[dict] = []
        notes: list[str] = []
        baseline_views: list[dict] = []
        run = Run(
            id=new_id(),
            dataset_id=dataset.id,
            label=body.label or f"重算基线 · {dataset.name}"[:100],
            parameter=parameter,
            actor=actor,
            status="running",
            started_at=utcnow(),
        )
        db.add(run)
        db.flush()

        for tier in tiers:
            plan = plan_tier(rows, tier, revoked)
            if not plan.ready:
                baseline = Baseline(
                    id=new_id(), run_id=run.id, dataset_id=dataset.id,
                    source_checksum=dataset.checksum, tier=tier,
                    status=BaselineStatus.SUSPENDED.value, parameter=parameter,
                    fit_reels=list(plan.fit_reels), holdout_reels=list(plan.holdout_reels),
                    used_reels=sorted(set(plan.fit_reels) | set(plan.holdout_reels)),
                    note=plan.reason, actor=actor, finished_at=utcnow(),
                    detail=plan.to_view(),
                )
                db.add(baseline)
                db.flush()
                baseline_views.append(baseline_view(baseline))
                notes.append(f"{tier} cm/s 档已暂停：{plan.reason}")
                continue

            try:
                scored = recompute_tier(rows, tier, parameter, revoked)
            except ValueError as exc:
                baseline = Baseline(
                    id=new_id(), run_id=run.id, dataset_id=dataset.id,
                    source_checksum=dataset.checksum, tier=tier,
                    status=BaselineStatus.SUSPENDED.value, parameter=parameter,
                    fit_reels=list(plan.fit_reels), holdout_reels=list(plan.holdout_reels),
                    used_reels=sorted(set(plan.fit_reels) | set(plan.holdout_reels)),
                    note=str(exc), actor=actor, finished_at=utcnow(),
                    detail=plan.to_view(),
                )
                db.add(baseline)
                db.flush()
                baseline_views.append(baseline_view(baseline))
                notes.append(f"{tier} cm/s 档无法完成：{exc}")
                continue

            combined_rows.extend(scored["results"])
            notes.append(scored["note"])
            baseline = Baseline(
                id=new_id(), run_id=run.id, dataset_id=dataset.id,
                source_checksum=dataset.checksum, tier=tier,
                status=BaselineStatus.ACTIVE.value, parameter=parameter,
                threshold=scored["threshold"], note=scored["note"],
                fit_reels=scored["fit_reels"], holdout_reels=scored["holdout_reels"],
                used_reels=sorted(set(scored["fit_reels"]) | set(scored["holdout_reels"])),
                actor=actor, finished_at=utcnow(),
                detail={"plan": scored.get("plan"), "explained_share": scored["explained_share"]},
            )
            prior = db.scalars(select(Baseline).where(Baseline.tier == tier)).all()
            baseline.generation = (max((b.generation or 0) for b in prior) + 1) if prior else 1
            db.add(baseline)
            db.flush()
            baseline_views.append(baseline_view(baseline))

        combined_rows.sort(key=lambda row: (-row["score"], row["sample_id"]))
        retransfer = sum(1 for r in combined_rows if str(r.get("decision", "")).startswith("建议复录"))
        run.status = "succeeded"
        run.finished_at = utcnow()
        run.result = {
            "summary": f"重算完成：{len(combined_rows)} 条试录段，{retransfer} 条建议复录；"
                       f"{sum(1 for b in baseline_views if b['status'] == 'suspended')} 档暂停。",
            "metrics": [
                {"label": "待检段", "value": len(combined_rows)},
                {"label": "建议复录", "value": retransfer},
                {"label": "通过校准", "value": len(combined_rows) - retransfer},
                {"label": "带速基线", "value": sum(1 for b in baseline_views if b["status"] == "active")},
            ],
            "rows": combined_rows,
            "notes": notes,
            "recompute": True,
            "baselines": baseline_views,
        }
        # Freeze a CSV artifact so the ordinary result export keeps working.
        try:
            from src.services.exports import result_keys
            artifact = f"{run.id}-recompute.csv"
            (ARTIFACTS / artifact).write_text(
                "﻿" + render_csv(combined_rows, result_keys(), protect=True), encoding="utf-8"
            )
            run.artifact = artifact
        except Exception:  # artifacts are optional in tests
            run.artifact = None

        record(db, actor, "baselines_recomputed", run.id)
        db.flush()
        response_run = run_view(run, include_result=True)

    return {"run": response_run, "baselines": _annotate_current(baseline_views)}
