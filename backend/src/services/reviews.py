from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.business.baselines import freeze_handoff
from src.config.settings import Session
from src.constants.workflow import Decision, Stage
from src.models.review import Review
from src.models.base import utcnow
from src.schemas.resources import review_view
from src.services import runs
from src.services.audit import record
from src.services.baselines import assert_run_signable


def lookup(db, run_id):
    return db.scalar(select(Review).where(Review.run_id == run_id))


def list_reviews():
    with Session() as db:
        return [review_view(review) for review in db.scalars(select(Review).order_by(Review.created_at.desc()))]


def sign(run_id, body, reviewer):
    with Session.begin() as db:
        run = runs.require(db, run_id)
        if run.status != Stage.SUCCEEDED.value:
            raise HTTPException(409, "计算成功后才能签审。")
        if lookup(db, run_id) is not None:
            raise HTTPException(409, "此计算单已有交接决定。")
        result_rows = (run.result or {}).get("rows", [])
        valid = {row["sample_id"] for row in result_rows}
        samples = list(dict.fromkeys(body.samples))
        if set(samples) - valid:
            raise HTTPException(422, "签审样本不属于这次计算。")
        if body.decision == Decision.APPROVE and not samples:
            raise HTTPException(422, "签发至少需要勾选一条结果。")

        snapshot = None
        if body.decision == Decision.APPROVE:
            # Issuance gate: every selected tier must still have a clean
            # baseline.  Raises 409 when a used reel was revoked / tier paused.
            assert_run_signable(db, run, samples)
            selected = set(samples)
            frozen_rows = [
                {**row, "reviewer": reviewer, "review_note": body.note}
                for row in result_rows if row["sample_id"] in selected
            ]
            snapshot = freeze_handoff(
                frozen_rows,
                run_id=run_id,
                dataset_id=run.dataset_id,
                parameter=run.parameter,
                reviewer=reviewer,
                note=body.note,
                decision=body.decision.value,
                signed_at=utcnow().isoformat(),
            )

        review = Review(
            run_id=run_id, decision=body.decision.value, samples=samples,
            note=body.note, reviewer=reviewer, snapshot=snapshot,
        )
        db.add(review)
        record(db, reviewer, f"review_{body.decision.value}", run_id)
        try:
            db.flush()
        except IntegrityError as exc:
            raise HTTPException(409, "此计算单已有交接决定。") from exc
        return review_view(review)
