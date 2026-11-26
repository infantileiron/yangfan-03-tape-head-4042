from fastapi import Response
from sqlalchemy import select

from src.business.profile import PROFILE
from src.config.settings import Session
from src.models.baseline import Baseline
from src.schemas.resources import baseline_view, dataset_view, review_view, run_view
from src.services import baselines, datasets, reviews, runs
from src.utils.csv_data import render_csv


def dataset_details(dataset_id):
    with Session() as db:
        return dataset_view(datasets.require(db, dataset_id), include_rows=True)


def dataset_csv(dataset_id):
    with Session() as db:
        dataset = datasets.require(db, dataset_id)
        contents = render_csv(dataset.rows, [field["key"] for field in PROFILE["columns"]])
        return Response(contents, media_type="text/csv", headers={
            "Content-Disposition": f'attachment; filename="{dataset_id}-input.csv"',
        })


def run_details(run_id):
    with Session() as db:
        run = runs.require(db, run_id)
        result = run_view(run, include_result=True)
        review = reviews.lookup(db, run_id)
        result["review"] = review_view(review) if review else None
        result["baselines"] = [
            baseline_view(row)
            for row in db.scalars(select(Baseline).where(Baseline.run_id == run.id).order_by(Baseline.tier))
        ]
        result["issuance"] = baselines.issuance_summary(db, run)
        return result
