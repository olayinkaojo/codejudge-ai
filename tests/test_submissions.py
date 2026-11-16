from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import Evaluation, Submission, Task
from tests.conftest import authenticate


def test_catalog_metadata_never_exposes_test_inputs(client, auth):
    response = client.get("/test-suites", headers=auth)
    assert response.status_code == 200
    assert response.json()[0]["test_count"] == 4
    assert all("cases" not in suite and "expected" not in suite for suite in response.json())
    assert client.get("/test-suites").status_code == 401


def test_immutable_source_and_suite_snapshot(client, auth, task, factory):
    source = "  # indentation is preserved\nprint(5)\n"
    response = client.post("/submissions", headers=auth, json={"task_id": task["id"], "source": source})
    assert response.status_code == 201 and "source" not in response.json()
    with factory() as db:
        row = db.scalar(select(Submission))
        assert row.source == source
        suite = db.get(Task, row.task_id).suite_spec
        assert suite["id"] == "sum-two-v1" and len(suite["cases"]) == 4
    assert (
        client.put(
            "/submissions/" + response.json()["id"], headers=auth, json={"source": "changed"}
        ).status_code
        == 404
    )


@pytest.mark.parametrize("source", ["", "x" * 16001, "\x00", "😀" * 9000, ["not source"]])
def test_source_validation(client, auth, task, source):
    response = client.post("/submissions", headers=auth, json={"task_id": task["id"], "source": source})
    assert response.status_code == 422


def test_submission_ownership_and_task_binding(client, auth, task, submission):
    other = authenticate(client, "bob")
    assert (
        client.post(
            "/submissions", headers=other, json={"task_id": task["id"], "source": "print(5)"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/evaluations",
            headers=other,
            json={"task_id": task["id"], "submission_reference": submission["id"]},
        ).status_code
        == 404
    )
    second = client.post(
        "/tasks",
        headers=auth,
        json={
            "title": "Second",
            "description": "A different problem statement",
            "test_suite_id": "sum-two-v1",
        },
    ).json()
    assert (
        client.post(
            "/evaluations",
            headers=auth,
            json={"task_id": second["id"], "submission_reference": submission["id"]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/evaluations", headers=auth, json={"task_id": task["id"], "submission_reference": str(uuid4())}
        ).status_code
        == 404
    )


def test_challenges_without_suite_fail_closed(client, auth):
    task = client.post(
        "/tasks", headers=auth, json={"title": "Draft", "description": "No automated tests yet"}
    ).json()
    assert task["test_suite_id"] is None
    assert (
        client.post(
            "/submissions", headers=auth, json={"task_id": task["id"], "source": "print(5)"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/evaluations", headers=auth, json={"task_id": task["id"], "submission_reference": str(uuid4())}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/tasks",
            headers=auth,
            json={
                "title": "Unknown",
                "description": "No such test suite exists",
                "test_suite_id": "unknown-v1",
            },
        ).status_code
        == 422
    )


def test_worker_rejects_wrong_suite_results(factory, client, auth, task, submission):
    client.post(
        "/evaluations", headers=auth, json={"task_id": task["id"], "submission_reference": submission["id"]}
    ).json()
    import httpx

    from app.worker import run_once
    from tests.test_worker import runner_result, settings

    wrong = runner_result()
    wrong["case_results"][0]["id"] = "other-case"
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=wrong))) as client:
        run_once(factory, settings(), client)
    with factory() as db:
        row = db.scalar(select(Evaluation))
        assert row.status == "failed" and row.error == "invalid_sandbox_result" and row.score is None
