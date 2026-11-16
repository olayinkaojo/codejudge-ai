import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select

from app.config import Settings
from app.models import Evaluation
from app.worker import claim

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL", "").startswith("postgresql"),
    reason="Requires dedicated PostgreSQL TEST_DATABASE_URL",
)


def test_concurrent_workers_claim_distinct_jobs(client, factory, task, auth):
    ids = set()
    for index in range(4):
        response = client.post(
            "/evaluations",
            headers=auth,
            json={
                "task_id": task["id"],
                "submission_reference": f"artifact-{index}",
            },
        )
        ids.add(response.json()["id"])
    barrier = Barrier(4)

    def take_job(_):
        barrier.wait(timeout=10)
        return claim(factory, Settings(_env_file=None))

    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = list(pool.map(take_job, range(4)))
    assert {str(job.id) for job in jobs} == ids
    assert claim(factory, Settings(_env_file=None)) is None


def test_skip_locked_does_not_block_on_other_worker(client, factory, task, auth):
    for index in range(2):
        client.post(
            "/evaluations",
            headers=auth,
            json={
                "task_id": task["id"],
                "submission_reference": f"artifact-{index}",
            },
        )
    with factory.begin() as db:
        locked = db.scalar(
            select(Evaluation).order_by(Evaluation.created_at, Evaluation.id).with_for_update().limit(1)
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            job = pool.submit(claim, factory, Settings(_env_file=None)).result(timeout=5)
        assert job.id != locked.id
