"""Reel qualification and baseline validity/recomputation endpoints."""

from fastapi import APIRouter, Depends

from src.routes.dependencies import current_account, staff
from src.schemas.requests import RecomputeRequest, RevocationRequest, RevokeReelRequest
from src.services import baselines, reels

router = APIRouter(dependencies=[Depends(current_account)])


# ---------------------------------------------------------------------------
# Qualified reels / revocation
# ---------------------------------------------------------------------------

@router.get("/reels")
def list_reels():
    return reels.list_reels()


@router.get("/qualified-reels")
def list_qualified_reels():
    return reels.list_reels()


@router.get("/qualifications")
def list_qualifications():
    return reels.list_reels()


@router.post("/qualifications/{reel}/revoke")
def revoke_qualification(reel: str, body: RevokeReelRequest | None = None, account=Depends(staff)):
    payload = body or RevokeReelRequest()
    return reels.revoke(reel, account.email, payload.reason, payload.tier)


@router.post("/reels/{reel}/revoke")
def revoke_reel(reel: str, body: RevokeReelRequest | None = None, account=Depends(staff)):
    payload = body or RevokeReelRequest()
    return reels.revoke(reel, account.email, payload.reason, payload.tier)


@router.post("/reels/{reel}/revocation")
def revoke_reel_alias(reel: str, body: RevokeReelRequest | None = None, account=Depends(staff)):
    payload = body or RevokeReelRequest()
    return reels.revoke(reel, account.email, payload.reason, payload.tier)


@router.post("/revocations")
def create_revocation(body: RevocationRequest, account=Depends(staff)):
    return reels.revoke(body.reel, account.email, body.reason, body.tier)


@router.post("/reels/revoke")
def revoke_reel_body(body: RevocationRequest, account=Depends(staff)):
    return reels.revoke(body.reel, account.email, body.reason, body.tier)


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------

@router.get("/baselines")
def list_baselines(tier: str | None = None, dataset_id: str | None = None):
    return baselines.list_baselines(tier=tier, dataset_id=dataset_id)


@router.get("/baseline")
def list_baselines_alias(tier: str | None = None, dataset_id: str | None = None):
    return baselines.list_baselines(tier=tier, dataset_id=dataset_id)


@router.get("/baselines/plan")
def baseline_plan(dataset_id: str):
    return baselines.plan_for_dataset(dataset_id)


@router.post("/baselines/plan")
def baseline_plan_post(body: RecomputeRequest):
    return baselines.plan_for_dataset(body.dataset_id)


@router.post("/baselines/recompute", status_code=200)
def recompute_baselines(body: RecomputeRequest, account=Depends(staff)):
    return baselines.recompute_now(body, account.email)


@router.post("/baseline/recompute", status_code=200)
def recompute_baselines_alias(body: RecomputeRequest, account=Depends(staff)):
    return baselines.recompute_now(body, account.email)


@router.post("/recompute", status_code=200)
def recompute_short(body: RecomputeRequest, account=Depends(staff)):
    return baselines.recompute_now(body, account.email)


# Declared after the fixed /baselines/... routes so "plan" is not captured.
@router.get("/baselines/{baseline_id}")
def baseline_detail(baseline_id: str):
    return baselines.get_baseline(baseline_id)
